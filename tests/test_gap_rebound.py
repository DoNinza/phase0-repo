from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.gap_rebound import PREREGISTERED_GRID, gap_rebound_signal


def _bg(date):
    return OhlcvBar(date=date, open=10000, high=10100, low=9900, close=10000, volume=1000)


def _baseline_bars():
    """D-1(마지막)이 트렌드 정상·평범한 21배경봉 세트. today_open과 조합해야 C2(갭) 충족."""
    bars = [_bg(f"D{i:02d}") for i in range(21)]
    y = OhlcvBar(date="D21", open=10050, high=10100, low=9950, close=10000, volume=1000)
    bars.append(y)
    return bars


BASELINE_OPEN = 10000 * 0.98   # 갭 -2% — C2 통과 (atr_pct≈1.96%, floor≈1.47%)


def test_preregistered_grid_has_six_combinations():
    assert len(PREREGISTERED_GRID) == 6
    assert (0.8, 1.0) in PREREGISTERED_GRID


def test_none_when_insufficient_history():
    bars = _baseline_bars()[:10]
    assert gap_rebound_signal(bars, BASELINE_OPEN, "D22") is None


def test_fires_when_all_conditions_met():
    bars = _baseline_bars()
    sig = gap_rebound_signal(bars, BASELINE_OPEN, "D22")
    assert sig is not None
    assert sig.entry_price == BASELINE_OPEN
    # 목표가는 갭 부분 되메움이라 진입가와 전일 종가(10000) 사이에 있어야 함
    assert sig.entry_price < sig.target_price < 10000
    assert sig.stop_price < sig.entry_price


def test_rejects_when_downtrend_context():
    bars = _baseline_bars()
    bars[-1] = OhlcvBar(date="D21", open=9550, high=9600, low=9450, close=9600, volume=1000)
    # sma20=(19*10000+9600)/20=9980 → 0.98*9980=9780.4, y.close=9600 < 9780.4 → C1 위반
    assert gap_rebound_signal(bars, 9600 * 0.98, "D22") is None


def test_rejects_when_gap_too_shallow():
    bars = _baseline_bars()
    assert gap_rebound_signal(bars, 10000 * 0.995, "D22") is None   # 갭 -0.5% < 1.2% 최소


def test_rejects_when_gap_too_deep():
    bars = _baseline_bars()
    assert gap_rebound_signal(bars, 10000 * 0.94, "D22") is None   # 갭 -6% > -4.5% 상한 초과


def test_rejects_when_prior_day_already_crashed():
    bars = _baseline_bars()
    bars[-2] = OhlcvBar(date="D20", open=10600, high=10700, low=10500, close=10600, volume=1000)
    # y.close(10000)/prev.close(10600)-1 = -0.0566 <= -0.05 → C3 위반
    assert gap_rebound_signal(bars, 10000 * 0.975, "D22") is None


def test_rejects_when_volatility_too_low():
    bars = [OhlcvBar(date=f"D{i:02d}", open=10000, high=10005, low=9995, close=10000, volume=1000)
            for i in range(21)]
    bars.append(OhlcvBar(date="D21", open=10010, high=10015, low=9990, close=10000, volume=1000))
    assert gap_rebound_signal(bars, 10000 * 0.98, "D22") is None


def test_rejects_ex_dividend_window_regardless_of_other_conditions():
    bars = _baseline_bars()
    assert gap_rebound_signal(bars, BASELINE_OPEN, "20261225") is None


def test_f_fill_and_k_stop_change_target_and_stop_price():
    bars = _baseline_bars()
    default_sig = gap_rebound_signal(bars, BASELINE_OPEN, "D22")
    fuller_fill_sig = gap_rebound_signal(bars, BASELINE_OPEN, "D22", f_fill=1.0, k_stop=1.5)

    assert fuller_fill_sig.target_price > default_sig.target_price   # 더 많이 되메움
    assert fuller_fill_sig.stop_price < default_sig.stop_price       # k_stop 커짐 → 손절 더 멀어짐
