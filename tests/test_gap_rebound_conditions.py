"""evaluate_conditions()의 조건별 불리언·중간값을 손계산 기대값으로 직접 검증.

test_gap_rebound.py의 _baseline_bars() 픽스처 패턴을 그대로 따르고, 각
중간값(sma20/atr_pct/gap/gap_floor/prev_day_return)을 손으로 계산해 못박는다.
단락(short-circuit) 규약(첫 실패 조건 이후 None)도 함께 확인한다.
"""

import pytest

from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.gap_rebound import GdrConditionReport, evaluate_conditions


def _bg(date):
    return OhlcvBar(date=date, open=10000, high=10100, low=9900, close=10000, volume=1000)


def _baseline_bars():
    """test_gap_rebound.py와 동일: 21개 배경봉 + D-1(=D21) 정상봉."""
    bars = [_bg(f"D{i:02d}") for i in range(21)]
    y = OhlcvBar(date="D21", open=10050, high=10100, low=9950, close=10000, volume=1000)
    bars.append(y)
    return bars


BASELINE_OPEN = 10000 * 0.98   # 갭 -2%


def test_all_conditions_pass_with_hand_computed_intermediates():
    r = evaluate_conditions(_baseline_bars(), BASELINE_OPEN, "20260715")

    assert r.insufficient_history is False
    # sma20: 최근 20종가 전부 10000 -> 10000
    assert r.sma20 == pytest.approx(10000.0)
    # atr14: 배경봉 TR=200(13개) + y봉 TR=150 -> (13*200+150)/14 = 2750/14
    assert r.atr_pct == pytest.approx((2750 / 14) / 10000)   # ≈0.0196428
    # gap = 9800/10000 - 1 = -0.02
    assert r.gap_pct == pytest.approx(-0.02)
    # gap_floor = max(0.012, 0.75*0.0196428) = 0.0147321...
    assert r.gap_floor == pytest.approx(max(0.012, 0.75 * (2750 / 14) / 10000))
    # prev_day_return = 10000/10000 - 1 = 0
    assert r.prev_day_return == pytest.approx(0.0)

    assert r.c1_trend_ok is True
    assert r.c2_gap_band_ok is True
    assert r.c3_no_prior_crash_ok is True
    assert r.c4_volatility_band_ok is True
    assert r.c5_not_ex_div_window_ok is True
    assert r.passed_all is True


def test_insufficient_history_leaves_everything_none():
    r = evaluate_conditions(_baseline_bars()[:10], BASELINE_OPEN, "20260715")
    assert r.insufficient_history is True
    assert r.passed_all is False
    for field in ("gap_pct", "atr_pct", "sma20", "gap_floor", "prev_day_return",
                  "c1_trend_ok", "c2_gap_band_ok", "c3_no_prior_crash_ok",
                  "c4_volatility_band_ok", "c5_not_ex_div_window_ok"):
        assert getattr(r, field) is None, f"{field}가 None이 아님"


def test_ex_div_window_short_circuits_before_computing_anything():
    # 배당락 창(12/22~12/31)이면 sma/atr/gap 계산 이전에 종료 -> C5만 False, 나머지 None.
    r = evaluate_conditions(_baseline_bars(), BASELINE_OPEN, "20261225")
    assert r.insufficient_history is False
    assert r.c5_not_ex_div_window_ok is False
    assert r.passed_all is False
    for field in ("gap_pct", "atr_pct", "sma20", "gap_floor", "prev_day_return",
                  "c1_trend_ok", "c2_gap_band_ok", "c3_no_prior_crash_ok",
                  "c4_volatility_band_ok"):
        assert getattr(r, field) is None, f"{field}가 None이 아님(배당락 단락 위반)"


def test_ex_div_window_boundaries_inclusive():
    bars = _baseline_bars()
    assert evaluate_conditions(bars, BASELINE_OPEN, "20261222").c5_not_ex_div_window_ok is False  # 창 시작
    assert evaluate_conditions(bars, BASELINE_OPEN, "20261231").c5_not_ex_div_window_ok is False  # 창 끝
    assert evaluate_conditions(bars, BASELINE_OPEN, "20261221").c5_not_ex_div_window_ok is True   # 하루 전
    assert evaluate_conditions(bars, BASELINE_OPEN, "20270101").c5_not_ex_div_window_ok is True   # 다음 해


def test_c1_fail_short_circuits_before_c2_c3_c4():
    bars = _baseline_bars()
    bars[-1] = OhlcvBar(date="D21", open=9550, high=9600, low=9450, close=9600, volume=1000)
    # sma20 = (19*10000 + 9600)/20 = 9980, 0.98*9980 = 9780.4, y.close=9600 < 9780.4 -> C1 위반
    r = evaluate_conditions(bars, 9600 * 0.98, "20260715")
    assert r.sma20 == pytest.approx(9980.0)
    assert r.c5_not_ex_div_window_ok is True
    assert r.c1_trend_ok is False
    # 단락: C1 실패 이후 값들은 계산되지 않음
    assert r.gap_floor is None
    assert r.prev_day_return is None
    assert r.c2_gap_band_ok is None
    assert r.c3_no_prior_crash_ok is None
    assert r.c4_volatility_band_ok is None
    assert r.passed_all is False


def test_c2_fail_when_gap_too_shallow_short_circuits_before_c3():
    r = evaluate_conditions(_baseline_bars(), 10000 * 0.995, "20260715")   # 갭 -0.5%
    assert r.c1_trend_ok is True
    assert r.gap_pct == pytest.approx(-0.005)
    assert r.gap_floor == pytest.approx(max(0.012, 0.75 * (2750 / 14) / 10000))
    assert r.c2_gap_band_ok is False
    assert r.prev_day_return is None   # C3 나눗셈 미도달(단락)
    assert r.c3_no_prior_crash_ok is None
    assert r.c4_volatility_band_ok is None
    assert r.passed_all is False


def test_c3_fail_when_prior_day_crashed_short_circuits_before_c4():
    bars = _baseline_bars()
    bars[-2] = OhlcvBar(date="D20", open=10600, high=10700, low=10500, close=10600, volume=1000)
    # prev_day_return = 10000/10600 - 1 = -0.05660 <= -0.05 -> C3 위반
    r = evaluate_conditions(bars, 10000 * 0.975, "20260715")
    assert r.c1_trend_ok is True
    assert r.c2_gap_band_ok is True
    assert r.prev_day_return == pytest.approx(10000 / 10600 - 1)
    assert r.c3_no_prior_crash_ok is False
    assert r.c4_volatility_band_ok is None   # 단락
    assert r.passed_all is False


def test_c4_fail_when_volatility_too_low_is_evaluated_last():
    bars = [OhlcvBar(date=f"D{i:02d}", open=10000, high=10005, low=9995, close=10000, volume=1000)
            for i in range(21)]
    bars.append(OhlcvBar(date="D21", open=10010, high=10015, low=9990, close=10000, volume=1000))
    # atr14 = (13*10 + 25)/14 = 155/14 -> atr_pct ≈ 0.001107 < 0.010 -> C4 위반
    r = evaluate_conditions(bars, 10000 * 0.98, "20260715")
    assert r.atr_pct == pytest.approx((155 / 14) / 10000)
    assert r.c1_trend_ok is True
    assert r.c2_gap_band_ok is True
    assert r.c3_no_prior_crash_ok is True
    assert r.c4_volatility_band_ok is False   # 마지막 조건 -> 단락 없이 평가됨
    assert r.passed_all is False


def test_report_is_dataclass_of_scalars():
    # 대시보드 페이로드에 스칼라만 담기 위한 계약 — 봉 이력은 절대 포함하지 않음.
    r = evaluate_conditions(_baseline_bars(), BASELINE_OPEN, "20260715")
    assert isinstance(r, GdrConditionReport)
    assert isinstance(r.passed_all, bool)
