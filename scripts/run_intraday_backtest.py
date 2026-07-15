#!/usr/bin/env python3
"""IVR(장중 VWAP 평균회귀) 전략을 실제 5분봉으로 백테스트 (2026-07-15).

pytest에는 포함하지 않는다 — 실데이터(키움 백필분) 대량 처리라 실행에
시간이 걸린다. 네트워크 호출은 없다(이미 축적된 data/minute_bars_kiwoom/
JSONL을 읽기만 한다).

일봉 G0(run_g0_backtest.py)와 달리 낙관/보수 이중 경로가 없다 — 분봉
순서로 목표/손절 중 무엇이 먼저 일어났는지 결정론적으로 알 수 있기
때문이다(phase0.backtest.intraday_backtester 참고). 그래서 판정도
더 단순한 3분기(표본부족/기각/통과)다.

표본 문턱(정정, 2026-07-15): 일봉 G0의 "거래일 500일 이상"은 10년치
데이터셋을 전제로 정한 값이라, 지금 1년치(약 255거래일) 데이터셋에는
그대로 못 쓴다 — 이론상 최댓값(255)을 절대 못 넘어 항상 "표본부족"으로
나온다. 대신 **그 백테스트에 실제로 존재하는 거래일 수 대비 비율**로
문턱을 정한다(MIN_TRADING_DAY_COVERAGE) — 데이터가 몇 년으로 늘어나도
같은 로직이 자동으로 맞게 스케일된다. 거래 건수 문턱(MIN_TRADES)은
표본 정밀도(CLT) 문제라 데이터 기간과 무관하게 그대로 둔다.

사용법: python scripts/run_intraday_backtest.py [--tickers T1,T2,...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from phase0.backtest.intraday_backtester import resolve_intraday_trade
from phase0.config.costs import base_breakdown
from phase0.data.candidate_batch import EXPANDED_CANDIDATES
from phase0.data.minute_bar_store import MinuteBar, load_bars, store_path
from phase0.strategy.ivr import FORCED_EXIT_TIME, PREREGISTERED_GRID, ivr_signal_for_day

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "data" / "minute_bars_kiwoom"

MIN_TRADES = 1000
MIN_TRADING_DAY_COVERAGE = 0.5   # 데이터셋에 실제 존재하는 거래일의 절반 이상에서 신호가 나야 함


def group_by_date(bars: list[MinuteBar]) -> dict[str, list[MinuteBar]]:
    by_date: dict[str, list[MinuteBar]] = {}
    for b in sorted(bars, key=lambda x: (x.date, x.time)):
        by_date.setdefault(b.date, []).append(b)
    return by_date


def verdict_for(e_trade: float, n_trades: int, n_trading_days: int, min_trading_days: int) -> str:
    if n_trades < MIN_TRADES or n_trading_days < min_trading_days:
        return "insufficient_sample"
    return "pass" if e_trade > 0 else "reject"


def main() -> None:
    args = sys.argv[1:]
    tickers = None
    for i, a in enumerate(args):
        if a == "--tickers":
            tickers = args[i + 1].split(",")
    if tickers is None:
        tickers = [p.stem for p in sorted(STORE_DIR.glob("*.jsonl"))]
        if not tickers:
            tickers = EXPANDED_CANDIDATES

    cost_base = base_breakdown().base_total
    print(f"IVR 장중 백테스트: {len(tickers)}종목, 비용(Base) = {cost_base * 100:.4f}%\n")

    by_date_by_ticker: dict[str, dict[str, list[MinuteBar]]] = {}
    for ticker in tickers:
        path = store_path(STORE_DIR, ticker)
        bars = load_bars(path)
        if not bars:
            print(f"  {ticker}: 분봉 데이터 없음 — 건너뜀")
            continue
        by_date_by_ticker[ticker] = group_by_date(bars)
        print(f"  {ticker}: {len(bars)}봉, {len(by_date_by_ticker[ticker])}거래일")

    all_available_dates: set[str] = set()
    for by_date in by_date_by_ticker.values():
        all_available_dates.update(by_date.keys())
    min_trading_days = round(len(all_available_dates) * MIN_TRADING_DAY_COVERAGE)
    print(
        f"\n데이터셋 전체 거래일 {len(all_available_dates)}일 → 표본 문턱: "
        f"거래 {MIN_TRADES}건 이상 & 거래일 {min_trading_days}일 이상"
        f"(전체의 {MIN_TRADING_DAY_COVERAGE:.0%})"
    )
    print(f"사전 등록 격자 {len(PREREGISTERED_GRID)}개 조합\n")
    header = f"{'d':>8}{'f':>8}{'k_stop':>8}{'신호수':>8}{'거래일':>8}{'승률':>9}{'E_trade':>11}   판정"
    print(header)
    print("-" * len(header))

    for d, f, k_stop in PREREGISTERED_GRID:
        all_trades = []
        signal_dates: set[str] = set()

        for ticker, by_date in by_date_by_ticker.items():
            dates_sorted = sorted(by_date.keys())
            for i in range(1, len(dates_sorted)):
                date = dates_sorted[i]
                prev_date = dates_sorted[i - 1]
                day_bars = by_date[date]
                prev_close = by_date[prev_date][-1].close

                sig = ivr_signal_for_day(ticker, day_bars, prev_close, d, f, k_stop)
                if sig is None:
                    continue
                trade = resolve_intraday_trade(day_bars, sig, FORCED_EXIT_TIME)
                all_trades.append(trade)
                signal_dates.add(date)

        n = len(all_trades)
        if n == 0:
            print(f"{d * 100:>7.2f}%{f:>8.2f}{k_stop:>8.2f}{0:>8}{0:>8}    —{'':>6}      —   insufficient_sample")
            continue

        pnls = [t.pnl_pct for t in all_trades]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x <= 0]
        p = len(wins) / n
        W = sum(wins) / len(wins) if wins else 0.0
        L = -sum(losses) / len(losses) if losses else 0.0
        e_trade = p * W - (1 - p) * L - cost_base
        n_trading_days = len(signal_dates)
        verdict = verdict_for(e_trade, n, n_trading_days, min_trading_days)

        print(
            f"{d * 100:>7.2f}%{f:>8.2f}{k_stop:>8.2f}{n:>8}{n_trading_days:>8}"
            f"{p * 100:>8.2f}%{e_trade * 100:>+10.4f}%   {verdict}"
        )


if __name__ == "__main__":
    main()
