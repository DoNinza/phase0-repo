#!/usr/bin/env python3
"""GDR 실거래 데이터에 이동 블록 부트스트랩 적용 — E_trade 신뢰구간 산출.

배경: 95종목 재실행으로 GDR은 이미 표본 기준(1,000건·500일)을 넘겨
"reject" 확정 판정을 받았다(README 참고, 최선 E_conservative −0.160%).
여기서 더 종목을 추가하는 건 "부호가 바뀌길 바라며 계속 시도"하는
데이터마이닝 위험이 있으므로, 대신 이미 확정된 −0.160%라는 점추정치가
통계적으로 0과 구분되는지(신뢰구간이 0을 포함하는지)를 부트스트랩으로
정량화한다. phase0.bootstrap.cluster_bootstrap은 지금까지 합성 데이터로만
검증됐다(README "남은 것") — 이 스크립트가 그 실전 배선 첫 단계다.

주의: 계좌 지표(CAGR·MDD)는 포지션 사이징 모델이 아직 없어 의미 있는
account_return을 만들 수 없다 — account_return은 0.0 placeholder로 채우고
계좌 지표는 산출·해석하지 않는다. 여기서 보는 건 오직 거래 단위 지표
(e_trade_gross에서 비용을 뺀 net E_trade)의 신뢰구간뿐이다.

사용법: python scripts/run_gdr_bootstrap.py [--universe default|expanded] [--years N]
"""

from __future__ import annotations

import datetime as dt
import sys

import numpy as np

from phase0.backtest.g0_backtester import resolve_trade
from phase0.bootstrap.cluster_bootstrap import DailyRecord, block_length_sensitivity
from phase0.config.costs import base_breakdown
from phase0.data.candidate_batch import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.pykrx_ingest import fetch_ohlcv, to_daily_bar
from phase0.strategy.gap_rebound import PREREGISTERED_GRID, gap_rebound_signal

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}


def generate_signals(bars, f_fill, k_stop):
    signals = []
    for i, b in enumerate(bars):
        history = bars[:i]   # D 이전(=D-1까지) — 룩어헤드 없음
        sig = gap_rebound_signal(history, b.open, b.date, f_fill=f_fill, k_stop=k_stop)
        if sig is not None:
            signals.append(sig)
    return signals


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

    print(f"GDR 부트스트랩: {len(tickers)}종목({universe}), {start}~{end}\n")

    raw_bars_by_ticker = {}
    for t in tickers:
        try:
            raw_bars_by_ticker[t] = fetch_ohlcv(t, start, end)
        except Exception as exc:
            print(f"  {t}: 수집 실패 ({type(exc).__name__}: {exc})")
    daily_bars_by_ticker = {
        t: {b.date: to_daily_bar(b) for b in bars} for t, bars in raw_bars_by_ticker.items()
    }

    cost_base = base_breakdown().base_total
    print(f"비용(Base, C) = {cost_base * 100:.4f}%\n")

    header = f"{'f_fill':>8}{'k_stop':>8}{'block':>7}{'point(net)':>12}{'CI_lo':>10}{'CI_hi':>10}   해석"
    print(header)
    print("-" * len(header))

    for f_fill, k_stop in PREREGISTERED_GRID:
        by_date: dict[str, list[dict]] = {}
        for t, bars in raw_bars_by_ticker.items():
            dbars = daily_bars_by_ticker[t]
            for sig in generate_signals(bars, f_fill, k_stop):
                bar = dbars[sig.date]
                tr = resolve_trade(bar, sig, "conservative")
                by_date.setdefault(sig.date, []).append({"pnl_pct": tr.pnl_pct, "is_win": tr.is_win})

        dates_sorted = sorted(by_date.keys())
        records = [DailyRecord(date=d, account_return=0.0, trades=by_date[d]) for d in dates_sorted]

        if len(records) < 20:
            print(f"{f_fill:>8.2f}{k_stop:>8.2f}   표본 부족(거래일 {len(records)} < 20) — 부트스트랩 생략")
            continue

        results = block_length_sensitivity(records, block_lengths=(10, 15, 20), n_resamples=1000)
        for bl in (10, 15, 20):
            gross = results[bl].trade_metrics["e_trade_gross"]
            net = gross - cost_base
            point = float(net.mean())
            lo, hi = float(np.percentile(net, 2.5)), float(np.percentile(net, 97.5))
            tag = "0 포함(0과 구분 안 됨)" if lo <= 0 <= hi else ("전부 음수" if hi < 0 else "전부 양수")
            print(
                f"{f_fill:>8.2f}{k_stop:>8.2f}{bl:>7}{point * 100:>+11.4f}%"
                f"{lo * 100:>+9.4f}%{hi * 100:>+9.4f}%   {tag}"
            )


if __name__ == "__main__":
    main()
