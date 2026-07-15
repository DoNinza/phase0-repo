#!/usr/bin/env python3
"""전략을 실제 KRX 일봉으로 G0 백테스트 (STAGE 7 항목 9·10).

pytest에는 포함하지 않는다 — 여러 종목·다년치 실제 네트워크 호출이라
시간이 걸리고 KRX 서버 상태에 좌우된다.

매일 D 이전(D-1까지)의 봉으로 전략의 신호 함수를 계산하고, D의 실제 시가를
넣어 신호를 만든다 — 미래 데이터를 보지 않는다(look-ahead 없음).

기본 동작은 그 전략의 사전 등록된 격자를 전부 돌려서 투명하게 보고한다 —
결과를 보고 나서 조합을 추가로 더 찾는 행위는 데이터마이닝이므로 하지
않는다. 네트워크 호출은 종목당 한 번만 하고(원본 일봉 캐시), 격자의 각
조합은 그 캐시된 데이터로 신호만 다시 계산한다.

사용법: python scripts/run_g0_backtest.py [--market kr|us|etf]
                                            [--strategy vcb_gap|gap_rebound|gap_rebound_v|vbp|all]
                                            [--years N] [--tickers T1,T2,...]
                                            [--universe default|expanded]

--market: kr은 pykrx/costs.yaml/candidate_batch(KOSPI), us는 yfinance/
us_costs.yaml/us_candidates(NYSE·NASDAQ) — 전략·백테스터·격자 로직은
시장에 무관하게 그대로 재사용된다(OhlcvBar/DailyBar 계약이 공통).
--strategy all: 종목 데이터를 한 번만 수집해 네 전략 전부의 격자를 그 위에서
돈다(종목 수가 많을 때 중복 네트워크 호출을 피하기 위함).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from phase0.backtest.g0_backtester import DailyBar, run_g0_multi
from phase0.config.costs import base_breakdown
from phase0.data import candidate_batch, etf_candidates, us_candidates
from phase0.data import pykrx_ingest, us_ingest
from phase0.data.pykrx_ingest import OhlcvBar, to_daily_bar
from phase0.strategy import gap_rebound, gap_rebound_v, vbp, vcb_gap

MARKETS = {
    "kr": {
        "fetch_ohlcv": pykrx_ingest.fetch_ohlcv,
        "universes": {"default": candidate_batch.DEFAULT_CANDIDATES,
                      "expanded": candidate_batch.EXPANDED_CANDIDATES},
        "costs_path": None,   # costs.py 기본값(costs.yaml) 사용
    },
    "us": {
        "fetch_ohlcv": us_ingest.fetch_ohlcv,
        "universes": {"default": us_candidates.DEFAULT_CANDIDATES,
                      "expanded": us_candidates.EXPANDED_CANDIDATES},
        "costs_path": Path(__file__).resolve().parents[1] / "phase0" / "config" / "us_costs.yaml",
    },
    "etf": {
        "fetch_ohlcv": pykrx_ingest.fetch_ohlcv,   # get_market_ohlcv가 ETF 코드에도 그대로 동작(실측 확인)
        "universes": {"default": etf_candidates.DEFAULT_CANDIDATES,
                      "expanded": etf_candidates.EXPANDED_CANDIDATES},
        "costs_path": Path(__file__).resolve().parents[1] / "phase0" / "config" / "etf_costs.yaml",
    },
}

STRATEGIES = {
    "vcb_gap": (vcb_gap.vcb_gap_signal, vcb_gap.PREREGISTERED_GRID, ("k_target", "k_stop")),
    "gap_rebound": (gap_rebound.gap_rebound_signal, gap_rebound.PREREGISTERED_GRID, ("f_fill", "k_stop")),
    "gap_rebound_v": (
        gap_rebound_v.gap_rebound_v_signal,
        gap_rebound_v.PREREGISTERED_GRID,
        ("f_fill", "k_stop", "v_mult"),
    ),
    "vbp": (vbp.vbp_signal, vbp.PREREGISTERED_GRID, ("f_ret", "k_stop")),
}


def build_daily_bars(bars: list[OhlcvBar]) -> dict[str, DailyBar]:
    return {b.date: to_daily_bar(b) for b in bars}


def generate_signals(bars: list[OhlcvBar], signal_fn, param_names, params) -> list:
    kwargs = dict(zip(param_names, params))
    signals = []
    for i, b in enumerate(bars):
        history = bars[:i]   # D 이전(=D-1까지) — D 당일 데이터는 절대 안 봄
        sig = signal_fn(history, b.open, b.date, **kwargs)
        if sig is not None:
            signals.append(sig)
    return signals


def run_strategy_grid(strategy_name, raw_bars_by_ticker, daily_bars_by_ticker, cost_base) -> None:
    signal_fn, grid, param_names = STRATEGIES[strategy_name]

    print(f"\n=== [{strategy_name}] 사전 등록 격자 {len(grid)}개 조합 (재수집 없음) ===")
    param_header = "".join(f"{p:>10}" for p in param_names)
    header = f"{param_header}{'신호수':>8}{'거래일':>8}{'충돌봉%':>9}{'E_cons':>11}{'E_opt':>11}   판정"
    print(header)
    print("-" * len(header))

    for params in grid:
        signals_by_ticker = {
            t: generate_signals(bars, signal_fn, param_names, params)
            for t, bars in raw_bars_by_ticker.items()
        }
        verdict = run_g0_multi(daily_bars_by_ticker, signals_by_ticker, cost_base=cost_base)
        param_values = "".join(f"{v:>10.3f}" for v in params)
        print(
            f"{param_values}{verdict.n_trades:>8}{verdict.n_trading_days:>8}"
            f"{verdict.ambiguous_ratio * 100:>8.2f}%{verdict.e_conservative * 100:>+10.4f}%"
            f"{verdict.e_optimistic * 100:>+10.4f}%   {verdict.verdict}"
        )


def main() -> None:
    market = "kr"
    strategy_name = "vcb_gap"
    years = 10
    universe = "default"
    tickers = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--market":
            market = args[i + 1]
        if a == "--strategy":
            strategy_name = args[i + 1]
        if a == "--years":
            years = int(args[i + 1])
        if a == "--tickers":
            tickers = args[i + 1].split(",")
        if a == "--universe":
            universe = args[i + 1]

    market_cfg = MARKETS[market]
    if tickers is None:
        tickers = market_cfg["universes"][universe]

    strategy_names = list(STRATEGIES.keys()) if strategy_name == "all" else [strategy_name]

    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=365 * years)).strftime("%Y%m%d")

    print(f"[{market}/{strategy_name}] {len(tickers)}종목({universe}), {start}~{end} 실데이터로 G0 백테스트 시작")
    print("(DEFAULT_CANDIDATES/EXPANDED_CANDIDATES는 손으로 고른 플레이스홀더 — README 참고)\n")

    raw_bars_by_ticker: dict[str, list[OhlcvBar]] = {}
    for ticker in tickers:
        try:
            raw_bars_by_ticker[ticker] = market_cfg["fetch_ohlcv"](ticker, start, end)
        except Exception as exc:
            print(f"  {ticker}: 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        print(f"  {ticker}: {len(raw_bars_by_ticker[ticker])}봉 수집")

    daily_bars_by_ticker = {t: build_daily_bars(bars) for t, bars in raw_bars_by_ticker.items()}
    costs_path = market_cfg["costs_path"]
    cost_base = base_breakdown(costs_path).base_total if costs_path else base_breakdown().base_total
    print(f"\n비용(Base, C) = {cost_base * 100:.4f}%")

    for name in strategy_names:
        run_strategy_grid(name, raw_bars_by_ticker, daily_bars_by_ticker, cost_base)


if __name__ == "__main__":
    main()
