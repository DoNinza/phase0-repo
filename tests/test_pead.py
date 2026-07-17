"""PEAD 전략 Phase 2 사전등록 상수 검증 (phase0/strategy/pead.py).

Phase 2 시점엔 신호 함수가 아직 없다(기획안 §8 로드맵 — 그건 Phase 3).
여기선 사전등록된 격자·상수가 기획안 §5/§10과 정확히 일치하는지만
검증한다 — 이 값들은 백테스트 결과를 보기 전에 확정됐으므로, 앞으로
바뀌면 안 된다는 걸 테스트로 고정한다.
"""

from phase0.data.dart_ingest import DartEvent
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.pead import (
    EX_DIV_WINDOW,
    H_GRID,
    K_STOP_GRID,
    LONG_ONLY,
    MIN_DISTINCT_DATES,
    MIN_EVENTS,
    PREREGISTERED_GRID,
    SUE_DENOMINATOR,
    THETA_GRID,
    compute_sue,
    pead_signal,
)


def test_preregistered_grid_has_eight_combinations():
    assert len(PREREGISTERED_GRID) == 8
    assert (0.03, 5, 1.5) in PREREGISTERED_GRID
    assert (0.10, 20, 2.5) in PREREGISTERED_GRID


def test_grid_is_full_cartesian_product():
    expected = {
        (theta, h, k) for theta in THETA_GRID for h in H_GRID for k in K_STOP_GRID
    }
    assert set(PREREGISTERED_GRID) == expected


def test_sue_denominator_is_sales():
    assert SUE_DENOMINATOR == "sales"


def test_theta_grid_values():
    assert THETA_GRID == (0.03, 0.10)


def test_h_grid_values():
    assert H_GRID == (5, 20)


def test_k_stop_grid_values():
    assert K_STOP_GRID == (1.5, 2.5)


def test_ex_div_window_matches_gdr_c5():
    from phase0.strategy.gap_rebound import EX_DIV_WINDOW as GDR_EX_DIV_WINDOW

    assert EX_DIV_WINDOW == GDR_EX_DIV_WINDOW == ("1222", "1231")


def test_long_only():
    assert LONG_ONLY is True


def test_min_sample_thresholds():
    assert MIN_EVENTS == 300
    assert MIN_DISTINCT_DATES == 150


def _op_event(op_current=100.0, op_prior=50.0, sales_current=1000.0, sales_prior=900.0):
    return DartEvent(
        ticker="005930", corp_code="00126380", rcept_no="1", rcept_dt="20260706",
        report_nm="연결재무제표기준영업(잠정)실적(공정공시)",
        op_income_current=op_current, op_income_prior_year_same_q=op_prior,
        sales_current=sales_current, sales_prior_year_same_q=sales_prior,
    )


def test_compute_sue_normal_case():
    event = _op_event(op_current=100.0, op_prior=50.0, sales_current=1000.0)
    assert compute_sue(event) == (100.0 - 50.0) / 1000.0


def test_compute_sue_none_when_op_missing():
    event = _op_event()
    event.op_income_current = None
    assert compute_sue(event) is None


def test_compute_sue_none_when_sales_missing():
    event = _op_event()
    event.sales_current = None
    assert compute_sue(event) is None


def test_compute_sue_none_when_sales_zero():
    event = _op_event(sales_current=0.0)
    assert compute_sue(event) is None


def _bar(date, o=10000.0, h=10100.0, l=9900.0, c=10000.0, v=1000):
    return OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=v)


def _baseline_bars(n=20):
    return [_bar(f"2026{(i % 12) + 1:02d}{(i % 27) + 1:02d}") for i in range(n)]


def test_pead_signal_none_when_insufficient_history():
    event = _op_event(op_current=100.0, op_prior=0.0, sales_current=1000.0)  # SUE=0.10
    sig = pead_signal(
        event, _baseline_bars(n=10), entry_open=10000.0, entry_date="20260707",
        theta=0.03, hold_days=5, k_stop=1.5,
    )
    assert sig is None


def test_pead_signal_none_when_sue_below_theta():
    event = _op_event(op_current=20.0, op_prior=0.0, sales_current=1000.0)  # SUE=0.02 < 0.03
    sig = pead_signal(
        event, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.03, hold_days=5, k_stop=1.5,
    )
    assert sig is None


def test_pead_signal_none_when_ex_dividend_window():
    event = _op_event(op_current=100.0, op_prior=0.0, sales_current=1000.0)
    sig = pead_signal(
        event, _baseline_bars(), entry_open=10000.0, entry_date="20261225",
        theta=0.03, hold_days=5, k_stop=1.5,
    )
    assert sig is None


def test_pead_signal_fires_when_conditions_met():
    event = _op_event(op_current=100.0, op_prior=0.0, sales_current=1000.0)  # SUE=0.10 >= 0.03
    sig = pead_signal(
        event, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.03, hold_days=5, k_stop=1.5,
    )
    assert sig is not None
    assert sig.ticker == "005930"
    assert sig.entry_date == "20260707"
    assert sig.entry_price == 10000.0
    assert sig.hold_days == 5
    assert sig.stop_price < sig.entry_price


def test_pead_signal_none_when_sue_uncomputable():
    event = _op_event()
    event.op_income_current = None
    sig = pead_signal(
        event, _baseline_bars(), entry_open=10000.0, entry_date="20260707",
        theta=0.03, hold_days=5, k_stop=1.5,
    )
    assert sig is None
