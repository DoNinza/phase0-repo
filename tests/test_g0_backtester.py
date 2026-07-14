from phase0.backtest.g0_backtester import (
    DailyBar, Signal, classify_bar, resolve_trade, run_g0, run_g0_multi, BarResolution,
)

COST_BASE = 0.0036  # Base 2026


def test_classify_target_hit():
    bar = DailyBar("D1", open=100, high=110, low=99, close=105)
    sig = Signal("D1", entry_price=100, target_price=108, stop_price=95)
    assert classify_bar(bar, sig) == BarResolution.TARGET_HIT


def test_classify_stop_hit():
    bar = DailyBar("D1", open=100, high=102, low=90, close=95)
    sig = Signal("D1", entry_price=100, target_price=108, stop_price=95)
    assert classify_bar(bar, sig) == BarResolution.STOP_HIT


def test_classify_ambiguous():
    bar = DailyBar("D1", open=100, high=110, low=90, close=95)
    sig = Signal("D1", entry_price=100, target_price=108, stop_price=95)
    assert classify_bar(bar, sig) == BarResolution.AMBIGUOUS


def test_resolve_ambiguous_conservative_is_stop():
    bar = DailyBar("D1", open=100, high=110, low=90, close=95)
    sig = Signal("D1", entry_price=100, target_price=108, stop_price=95)
    trade = resolve_trade(bar, sig, "conservative")
    assert trade.resolution == BarResolution.AMBIGUOUS
    assert trade.pnl_pct == (95 - 100) / 100


def test_resolve_ambiguous_optimistic_is_target_then_close():
    bar = DailyBar("D1", open=100, high=110, low=90, close=103)
    sig = Signal("D1", entry_price=100, target_price=108, stop_price=95)
    trade = resolve_trade(bar, sig, "optimistic")
    assert trade.resolution == BarResolution.AMBIGUOUS
    assert trade.pnl_pct == (103 - 108) / 108  # 목표가 진입 → 종가 청산


def _all_target_hits(n=1200):
    bars, sigs = {}, []
    for i in range(n):
        d = f"D{i:04d}"
        bars[d] = DailyBar(d, open=100, high=110, low=99, close=105)
        sigs.append(Signal(d, entry_price=100, target_price=105, stop_price=95))
    return bars, sigs


def test_run_g0_pass_when_both_paths_positive():
    bars, sigs = _all_target_hits()
    verdict = run_g0(bars, sigs, cost_base=COST_BASE)
    assert verdict.verdict == "pass"
    assert verdict.e_conservative > 0
    assert verdict.e_optimistic > 0


def _all_stop_hits(n=1200):
    bars, sigs = {}, []
    for i in range(n):
        d = f"D{i:04d}"
        bars[d] = DailyBar(d, open=100, high=101, low=90, close=93)
        sigs.append(Signal(d, entry_price=100, target_price=108, stop_price=92))
    return bars, sigs


def test_run_g0_reject_when_optimistic_also_negative():
    bars, sigs = _all_stop_hits()
    verdict = run_g0(bars, sigs, cost_base=COST_BASE)
    assert verdict.verdict == "reject"


def test_run_g0_insufficient_bar_power_when_ambiguous_ratio_high():
    n = 1200
    bars, sigs = {}, []
    for i in range(n):
        d = f"D{i:04d}"
        # 90%를 충돌 봉으로
        if i < int(n * 0.9):
            bars[d] = DailyBar(d, open=100, high=110, low=90, close=100)
        else:
            bars[d] = DailyBar(d, open=100, high=110, low=99, close=105)
        sigs.append(Signal(d, entry_price=100, target_price=108, stop_price=95))
    verdict = run_g0(bars, sigs, cost_base=COST_BASE)
    assert verdict.verdict == "insufficient_bar_power"
    assert verdict.ambiguous_ratio > 0.40


def test_run_g0_insufficient_sample_below_minimum():
    bars, sigs = _all_target_hits(n=10)
    verdict = run_g0(bars, sigs, cost_base=COST_BASE)
    assert verdict.verdict == "insufficient_sample"


def test_run_g0_multi_aggregates_across_tickers_and_handles_shared_dates():
    # run_g0()은 bars가 날짜만으로 키가 잡혀 있어 서로 다른 종목이 같은
    # 날짜를 쓰면 충돌한다 — run_g0_multi는 종목별 bars를 분리해서 이 문제를 피한다.
    bars_a, sigs_a = _all_target_hits(n=700)
    bars_b, sigs_b = _all_target_hits(n=700)   # 같은 날짜(D0000..)를 쓰는 별도 종목
    verdict = run_g0_multi(
        {"TICKER_A": bars_a, "TICKER_B": bars_b},
        {"TICKER_A": sigs_a, "TICKER_B": sigs_b},
        cost_base=COST_BASE,
    )
    assert verdict.n_trades == 1400
    assert verdict.n_trading_days == 700   # 날짜가 겹치므로 고유 날짜 수는 700
    assert verdict.verdict == "pass"


def test_run_g0_multi_matches_single_ticker_run_g0():
    bars, sigs = _all_target_hits(n=1200)
    single = run_g0(bars, sigs, cost_base=COST_BASE)
    multi = run_g0_multi({"ONLY": bars}, {"ONLY": sigs}, cost_base=COST_BASE)
    assert multi.verdict == single.verdict
    assert multi.n_trades == single.n_trades
    assert multi.e_conservative == single.e_conservative
    assert multi.e_optimistic == single.e_optimistic
