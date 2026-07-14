import pytest

from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vcb_gap import (
    PREREGISTERED_GRID, round_up_to_tick, tick_size, vcb_gap_signal,
)


def _bg(date):
    """평탄한 배경 봉: 20일 고점/거래량 평균의 기준선 역할."""
    return OhlcvBar(date=date, open=10000, high=10100, low=9900, close=10000, volume=1000)


def _baseline_bars():
    """D-1(마지막)이 돌파+거래량+범위+갭 조건을 전부 만족하는 22봉 세트."""
    bars = [_bg(f"D{i:02d}") for i in range(21)]   # D-22..D-2 배경봉 21개
    y = OhlcvBar(date="D21", open=10000, high=10350, low=10000, close=10300, volume=2000)
    bars.append(y)   # D-1: 강한 돌파 마감
    return bars


BASELINE_OPEN = 10300 * 1.005   # 시가 갭 +0.5% — C4 통과


def test_tick_size_boundaries():
    assert tick_size(1999) == 1
    assert tick_size(2001) == 5
    assert tick_size(50001) == 100
    assert tick_size(500001) == 1000


def test_round_up_to_tick_rounds_up_not_down():
    assert round_up_to_tick(50001) == 50100
    assert round_up_to_tick(2000) == 2000   # 정확히 경계면 그대로


def test_vcb_gap_signal_none_when_insufficient_history():
    bars = _baseline_bars()[:10]   # 22개 미만
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_vcb_gap_signal_fires_when_all_conditions_met():
    bars = _baseline_bars()
    sig = vcb_gap_signal(bars, BASELINE_OPEN, "D22")
    assert sig is not None
    assert sig.entry_price == BASELINE_OPEN
    assert sig.target_price > sig.entry_price
    assert sig.stop_price < sig.entry_price


def test_rejects_when_close_not_above_open_or_weak_clv():
    bars = _baseline_bars()
    # C1 위반: 종가가 시가보다 낮음(약세 마감), 다른 조건은 그대로 두기 위해
    # hh20(10100)보다는 여전히 높게 유지하지 않음 — 어차피 C1에서 먼저 걸림.
    bars[-1] = OhlcvBar(date="D21", open=10400, high=10450, low=10000, close=10300, volume=2000)
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_rejects_when_no_breakout_above_hh20():
    bars = _baseline_bars()
    # 배경봉들의 고점을 올려서 hh20이 D-1 종가보다 높아지게 만듦 (C2 위반)
    bars[1:21] = [OhlcvBar(date=b.date, open=b.open, high=10400, low=b.low,
                            close=b.close, volume=b.volume) for b in bars[1:21]]
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_rejects_when_volume_not_confirmed():
    bars = _baseline_bars()
    bars[-1] = OhlcvBar(date="D21", open=10000, high=10350, low=10000, close=10300, volume=1000)
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_rejects_when_gap_down_too_much():
    bars = _baseline_bars()
    assert vcb_gap_signal(bars, 10300 * 0.98, "D22") is None   # gap -2%


def test_rejects_when_gap_up_too_much():
    bars = _baseline_bars()
    assert vcb_gap_signal(bars, 10300 * 1.05, "D22") is None   # gap +5%


def test_rejects_when_volatility_too_low():
    bars = [OhlcvBar(date=f"D{i:02d}", open=10000, high=10005, low=9995, close=10000, volume=1000)
            for i in range(21)]
    bars.append(OhlcvBar(date="D21", open=10000, high=10350, low=10000, close=10300, volume=2000))
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_rejects_when_prior_day_near_limit_up():
    bars = _baseline_bars()
    bars[-2] = OhlcvBar(date="D20", open=9300, high=9400, low=9200, close=9300, volume=1000)
    assert vcb_gap_signal(bars, BASELINE_OPEN, "D22") is None


def test_preregistered_grid_has_six_combinations():
    assert len(PREREGISTERED_GRID) == 6
    assert (1.5, 1.0) in PREREGISTERED_GRID   # 기본값과 일치해야 함


def test_k_target_and_k_stop_change_target_and_stop_price():
    bars = _baseline_bars()
    default_sig = vcb_gap_signal(bars, BASELINE_OPEN, "D22")
    wider_sig = vcb_gap_signal(bars, BASELINE_OPEN, "D22", k_target=2.0, k_stop=0.75)

    assert wider_sig.target_price > default_sig.target_price   # k_target 커짐 → 목표가 더 멀어짐
    assert wider_sig.stop_price > default_sig.stop_price       # k_stop 작아짐 → 손절가 진입가에 더 가까워짐
    assert wider_sig.entry_price == default_sig.entry_price
