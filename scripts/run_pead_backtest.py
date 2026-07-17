#!/usr/bin/env python3
"""PEAD Phase 3 백테스트 — 8칸 사전등록 격자 전수 실행 + 이동블록
부트스트랩 CI (docs/news_fundamentals_전략_기획안.md §5·§7).

scripts/collect_dart_events.py로 이미 수집된 data/dart_events/*.jsonl
이벤트에 대해, 종목별 10년 일봉(pykrx 라이브 조회 — run_gdr_bootstrap.py와
동일 패턴, 별도 캐시 없음)을 기준으로 D+1 시가 진입 신호를 만들고
event_backtester로 해소한다. 8칸 전수 보고 — 최선 칸만 골라 채택하지
않는다(§5). 최소표본 문턱(MIN_EVENTS/MIN_DISTINCT_DATES, §5) 미달 칸은
부트스트랩 생략하고 그 사실을 그대로 표시한다.

블록 길이는 GDR(10/15/20일 고정)과 달리 보유기간 H에 비례해
{H, 1.5H, 2H}로 잡는다(§7 — "블록 길이 >= H").

사용법: python scripts/run_pead_backtest.py [--universe default|expanded] [--years N]
"""

from __future__ import annotations

import bisect
import datetime as dt
import sys
from pathlib import Path

import numpy as np

from phase0.backtest.event_backtester import resolve_event_trade
from phase0.backtest.g0_backtester import DailyBar
from phase0.bootstrap.cluster_bootstrap import DailyRecord, moving_block_bootstrap
from phase0.config.costs import base_breakdown
from phase0.data.candidate_batch import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.dart_ingest import load_events, store_path
from phase0.data.pykrx_ingest import fetch_ohlcv, to_daily_bar
from phase0.strategy.pead import (
    MIN_DISTINCT_DATES,
    MIN_EVENTS,
    MONOTONICITY_PREDICTION,
    PREREGISTERED_GRID,
    pead_signal,
)

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}
EVENTS_DIR = Path(__file__).resolve().parents[1] / "data" / "dart_events"

ATR_HISTORY_WINDOW = 20  # pead_signal의 MIN_ATR_HISTORY(15)에 여유를 둔 슬라이스 크기


def _find_entry_index(dates: list[str], rcept_dt: str) -> tuple[int, int] | None:
    """rcept_dt 이하 마지막 거래일 인덱스(history_end)와 그 다음 거래일
    (entry) 인덱스. 이력이 아예 없거나(상장 직후) entry가 아직 데이터
    범위를 벗어나면(최근 이벤트, 미래 데이터 없음) None."""
    pos = bisect.bisect_right(dates, rcept_dt)
    history_end, entry_idx = pos - 1, pos
    if history_end < 0 or entry_idx >= len(dates):
        return None
    return history_end, entry_idx


def main() -> None:
    universe = "expanded"
    years = 10
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--universe":
            universe = args[i + 1]
        if a == "--years":
            years = int(args[i + 1])
    tickers = UNIVERSES[universe]

    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=365 * years)).strftime("%Y%m%d")

    print(f"PEAD 백테스트: {len(tickers)}종목({universe}), 가격 {start}~{end}\n")

    print("[1/3] 이벤트 로드")
    events_by_ticker = {}
    total_events = 0
    for t in tickers:
        evs = load_events(store_path(EVENTS_DIR, t))
        if evs:
            events_by_ticker[t] = evs
            total_events += len(evs)
    print(f"  {len(events_by_ticker)}종목, 총 {total_events}건 이벤트 로드\n")

    if total_events == 0:
        print("이벤트가 없습니다 — scripts/collect_dart_events.py를 먼저 실행하세요.")
        sys.exit(1)

    print("[2/3] 일봉 가격 수집(pykrx, 라이브 조회)")
    daily_bars_by_ticker: dict[str, list[DailyBar]] = {}
    for i, t in enumerate(events_by_ticker, 1):
        try:
            raw = fetch_ohlcv(t, start, end)
        except Exception as exc:  # noqa: BLE001 — 종목 단위 격리
            print(f"  {t}: 가격 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        daily_bars_by_ticker[t] = [to_daily_bar(b) for b in raw]
        if i % 20 == 0 or i == len(events_by_ticker):
            print(f"  {i}/{len(events_by_ticker)}종목 완료")
    print()

    cost_base = base_breakdown().base_total
    print(f"비용(Base, C) = {cost_base * 100:.4f}%\n")

    print("[3/3] 8칸 격자 전수 백테스트 + 부트스트랩\n")
    header = (
        f"{'theta':>7}{'H':>4}{'k_stop':>8}{'n_trades':>10}{'n_dates':>9}{'block':>7}"
        f"{'point(net)':>12}{'CI_lo':>10}{'CI_hi':>10}   해석"
    )
    print(header)
    print("-" * len(header))

    monotonicity_check: dict[tuple[int, float], dict[float, float]] = {}

    for theta, H, k_stop in PREREGISTERED_GRID:
        by_date: dict[str, list[dict]] = {}
        for t, events in events_by_ticker.items():
            bars = daily_bars_by_ticker.get(t)
            if not bars:
                continue
            dates = [b.date for b in bars]
            for ev in events:
                idx = _find_entry_index(dates, ev.rcept_dt)
                if idx is None:
                    continue
                history_end, entry_idx = idx
                if entry_idx + H >= len(bars):
                    continue  # 아직 H거래일치 미래 데이터 없음(최근 이벤트)
                history = bars[max(0, history_end - ATR_HISTORY_WINDOW): history_end + 1]
                entry_bar = bars[entry_idx]
                sig = pead_signal(
                    ev, history, entry_bar.open, entry_bar.date,
                    theta=theta, hold_days=H, k_stop=k_stop,
                )
                if sig is None:
                    continue
                trade_bars = bars[entry_idx: entry_idx + H + 1]
                tr = resolve_event_trade(trade_bars, sig)
                by_date.setdefault(sig.entry_date, []).append(
                    {"pnl_pct": tr.pnl_pct, "is_win": tr.is_win}
                )

        n_trades = sum(len(v) for v in by_date.values())
        n_dates = len(by_date)

        if n_dates < MIN_DISTINCT_DATES or n_trades < MIN_EVENTS:
            print(
                f"{theta:>7.2f}{H:>4}{k_stop:>8.1f}{n_trades:>10}{n_dates:>9}   표본 부족"
                f"(거래일 {n_dates}<{MIN_DISTINCT_DATES} 또는 거래 {n_trades}<{MIN_EVENTS}) — 부트스트랩 생략"
            )
            continue

        dates_sorted = sorted(by_date.keys())
        records = [DailyRecord(date=d, account_return=0.0, trades=by_date[d]) for d in dates_sorted]

        block_lengths = sorted({H, round(H * 1.5), H * 2})
        for bl in block_lengths:
            result = moving_block_bootstrap(records, block_length=bl, n_resamples=1000)
            gross = result.trade_metrics["e_trade_gross"]
            net = gross - cost_base
            point = float(net.mean())
            lo, hi = float(np.percentile(net, 2.5)), float(np.percentile(net, 97.5))
            tag = "0 포함(0과 구분 안 됨)" if lo <= 0 <= hi else ("전부 음수" if hi < 0 else "전부 양수")
            print(
                f"{theta:>7.2f}{H:>4}{k_stop:>8.1f}{n_trades:>10}{n_dates:>9}{bl:>7}"
                f"{point * 100:>+11.4f}%{lo * 100:>+9.4f}%{hi * 100:>+9.4f}%   {tag}"
            )
            if bl == block_lengths[0]:
                monotonicity_check.setdefault((H, k_stop), {})[theta] = point

    print("\n" + "=" * 60)
    print("사전등록 반증 가능 예측 확인:", MONOTONICITY_PREDICTION)
    for (H, k_stop), by_theta in sorted(monotonicity_check.items()):
        thetas_sorted = sorted(by_theta.keys())
        points = [by_theta[t] for t in thetas_sorted]
        monotone = all(points[i] <= points[i + 1] for i in range(len(points) - 1))
        formatted = [f"{p * 100:+.4f}%" for p in points]
        print(
            f"  H={H}, k_stop={k_stop}: theta={thetas_sorted} -> point={formatted} "
            f"— 단조성 {'성립' if monotone else '깨짐'}"
        )


if __name__ == "__main__":
    main()
