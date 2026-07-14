from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.gap_rebound import gap_rebound_signal
from phase0.strategy.gap_rebound_v import PREREGISTERED_GRID, gap_rebound_v_signal


def _bg(date, volume=1000):
    return OhlcvBar(date=date, open=10000, high=10100, low=9900, close=10000, volume=volume)


def _baseline_bars(y_volume=1000):
    """D-1(마지막)이 트렌드 정상·평범한 21배경봉 세트. today_open과 조합해야 C2(갭) 충족.
    거래량은 전부 1000(평균)으로 고정하고, y_volume만 바꿔 C6(거래량 확인) 배율을 조절한다."""
    bars = [_bg(f"D{i:02d}") for i in range(21)]
    y = OhlcvBar(date="D21", open=10050, high=10100, low=9950, close=10000, volume=y_volume)
    bars.append(y)
    return bars


BASELINE_OPEN = 10000 * 0.98   # 갭 -2% — C2 통과 (atr_pct≈1.96%, floor≈1.47%)


def test_preregistered_grid_has_twelve_combinations():
    assert len(PREREGISTERED_GRID) == 12
    assert (0.8, 1.0, 1.5) in PREREGISTERED_GRID


def test_none_when_insufficient_history():
    bars = _baseline_bars(y_volume=2000)[:10]
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22") is None


def test_underlying_gdr_fires_but_gdr_v_rejects_without_volume_confirmation():
    """C1~C5는 만족(원 GDR은 발동)하지만 거래량이 평균 수준(C6 미충족)이면 GDR-V는 거부."""
    bars = _baseline_bars(y_volume=1000)   # 평균 대비 1.0배 — 1.2/1.5 배율 둘 다 미달
    assert gap_rebound_signal(bars, BASELINE_OPEN, "D22") is not None
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.2) is None
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.5) is None


def test_fires_when_volume_confirmed_matches_underlying_gdr_signal():
    bars = _baseline_bars(y_volume=2000)   # 평균 대비 2.0배 — 1.2/1.5 배율 둘 다 통과
    base_sig = gap_rebound_signal(bars, BASELINE_OPEN, "D22")
    v_sig = gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.5)
    assert v_sig is not None
    assert v_sig.entry_price == base_sig.entry_price
    assert v_sig.target_price == base_sig.target_price
    assert v_sig.stop_price == base_sig.stop_price


def test_rejects_when_prior_window_has_zero_volume_day():
    bars = _baseline_bars(y_volume=3000)
    bars[10] = OhlcvBar(date=bars[10].date, open=10000, high=10100, low=9900, close=10000, volume=0)
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.5) is None


def test_rejects_when_capital_event_day_in_window():
    bars = _baseline_bars(y_volume=3000)
    # bars[10] 종가가 전일 대비 40% 급변 — 자본이벤트로 추정, 위생 규칙에서 스킵
    bars[10] = OhlcvBar(date=bars[10].date, open=14000, high=14100, low=13900, close=14000, volume=1000)
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.5) is None


def test_higher_v_mult_is_stricter():
    bars = _baseline_bars(y_volume=1300)   # 평균 대비 1.3배 — 1.2배는 통과, 1.5배는 미달
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.2) is not None
    assert gap_rebound_v_signal(bars, BASELINE_OPEN, "D22", v_mult=1.5) is None
