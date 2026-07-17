"""FFD(Foreign Flow Drift) 전략 Phase 2 사전등록 상수 검증 (phase0/strategy/nat_flow.py).

test_pead.py와 동일한 스타일: 사전등록된 격자·상수가 기획안 §5/§10과
정확히 일치하는지 고정하고, 신호 함수(compute_signal_strength/
nat_flow_signal)의 조건별 판정을 단위 테스트한다. 이 값들은 백테스트
결과를 보기 전에 확정됐으므로, 앞으로 바뀌면 안 된다.
"""

from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.nat_flow import (
    DailyFlow,
    EX_DIV_WINDOW,
    H_GRID,
    K_STOP_GRID,
    LONG_ONLY,
    MIN_DISTINCT_DATES,
    MIN_EVENTS,
    NO_REENTRY_WHILE_HOLDING,
    PREREGISTERED_GRID,
    SIGNAL_DENOMINATOR,
    THETA_GRID,
    compute_signal_strength,
    nat_flow_signal,
)


def test_preregistered_grid_has_eight_combinations():
    assert len(PREREGISTERED_GRID) == 8
    assert (0.05, 5, 1.5) in PREREGISTERED_GRID
    assert (0.10, 20, 2.5) in PREREGISTERED_GRID


def test_grid_is_full_cartesian_product():
    expected = {
        (theta, h, k) for theta in THETA_GRID for h in H_GRID for k in K_STOP_GRID
    }
    assert set(PREREGISTERED_GRID) == expected


def test_signal_denominator_is_ohlcv_total_value():
    assert SIGNAL_DENOMINATOR == "ohlcv_total_value"


def test_theta_grid_values():
    assert THETA_GRID == (0.05, 0.10)


def test_h_grid_values():
    assert H_GRID == (5, 20)


def test_k_stop_grid_values():
    assert K_STOP_GRID == (1.5, 2.5)


def test_ex_div_window_matches_gdr_c5():
    from phase0.strategy.gap_rebound import EX_DIV_WINDOW as GDR_EX_DIV_WINDOW
    from phase0.strategy.pead import EX_DIV_WINDOW as PEAD_EX_DIV_WINDOW

    assert EX_DIV_WINDOW == GDR_EX_DIV_WINDOW == PEAD_EX_DIV_WINDOW == ("1222", "1231")


def test_long_only():
    assert LONG_ONLY is True


def test_no_reentry_while_holding():
    assert NO_REENTRY_WHILE_HOLDING is True


def test_min_sample_thresholds():
    assert MIN_EVENTS == 300
    assert MIN_DISTINCT_DATES == 150


def _flow(ticker, date, net, total):
    return DailyFlow(ticker=ticker, date=date, foreign_value_net=net, total_value=total)


def _flows_window(n=5, ticker="005930", net_per_day=60.0, total_per_day=1000.0, start_day=1):
    return [
        _flow(ticker, f"202607{start_day + i:02d}", net_per_day, total_per_day)
        for i in range(n)
    ]


def test_compute_signal_strength_normal_case():
    flows = _flows_window(n=5, net_per_day=60.0, total_per_day=1000.0)
    # sum(net)=300, sum(total)=5000 -> 0.06
    assert compute_signal_strength(flows, 5) == 300.0 / 5000.0


def test_compute_signal_strength_none_when_insufficient_history():
    flows = _flows_window(n=3)
    assert compute_signal_strength(flows, 5) is None


def test_compute_signal_strength_none_when_denominator_zero():
    flows = [_flow("005930", "20260701", 0.0, 0.0) for _ in range(5)]
    assert compute_signal_strength(flows, 5) is None


def test_compute_signal_strength_uses_only_last_n():
    # 앞쪽에 강도 0인 날짜를 섞어도 최근 n일만 반영돼야 한다.
    stale = [_flow("005930", f"202606{d:02d}", -1000.0, 1000.0) for d in range(1, 6)]
    fresh = _flows_window(n=5, net_per_day=60.0, total_per_day=1000.0, start_day=1)
    flows = stale + fresh
    assert compute_signal_strength(flows, 5) == 300.0 / 5000.0


def _bar(date, o=10000.0, h=10100.0, l=9900.0, c=10000.0, v=1000):
    return OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=v)


def _baseline_bars(n=20):
    return [_bar(f"2026{(i % 12) + 1:02d}{(i % 27) + 1:02d}") for i in range(n)]


def test_nat_flow_signal_none_when_insufficient_atr_history():
    flows = _flows_window(n=5, net_per_day=100.0, total_per_day=1000.0)  # R_5 = 0.10
    sig = nat_flow_signal(
        flows, _baseline_bars(n=10), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=1.5,
    )
    assert sig is None


def test_nat_flow_signal_none_when_below_theta():
    flows = _flows_window(n=5, net_per_day=20.0, total_per_day=1000.0)  # R_5 = 0.02 < 0.05
    sig = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=1.5,
    )
    assert sig is None


def test_nat_flow_signal_none_when_ex_dividend_window():
    flows = _flows_window(n=5, net_per_day=100.0, total_per_day=1000.0)  # R_5 = 0.10
    sig = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20261225",
        theta=0.05, h=5, k_stop=1.5,
    )
    assert sig is None


def test_nat_flow_signal_none_when_signal_uncomputable():
    flows = _flows_window(n=3, net_per_day=100.0, total_per_day=1000.0)  # h=5인데 3일치뿐
    sig = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=1.5,
    )
    assert sig is None


def test_nat_flow_signal_fires_when_conditions_met():
    flows = _flows_window(n=5, ticker="005930", net_per_day=100.0, total_per_day=1000.0)  # R_5=0.10
    sig = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=1.5,
    )
    assert sig is not None
    assert sig.ticker == "005930"
    assert sig.entry_date == "20260707"
    assert sig.entry_price == 10000.0
    assert sig.hold_days == 5
    assert sig.stop_price < sig.entry_price


def test_nat_flow_signal_stop_price_widens_with_larger_k_stop():
    flows = _flows_window(n=5, net_per_day=100.0, total_per_day=1000.0)
    sig_tight = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=1.5,
    )
    sig_wide = nat_flow_signal(
        flows, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.05, h=5, k_stop=2.5,
    )
    assert sig_wide.stop_price <= sig_tight.stop_price
