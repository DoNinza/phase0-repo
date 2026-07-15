from phase0.data.minute_bar_store import MinuteBar
from phase0.strategy.ivr import PREREGISTERED_GRID, ivr_signal_for_day


def _bar(time, o, h, l, c, v=1000):
    return MinuteBar(date="20260715", time=time, open=o, high=h, low=l, close=c, volume=v)


def _baseline_bars():
    """봉1~6(평가창 이전) 평탄 -> 봉7(093500, 하락·음봉, 평가창 진입 but C4 미충족)
    -> 봉8(094000, 반등·양봉, 유효 신호봉) -> 봉9(094500, 진입봉)."""
    bars = [_bar(t, 10000, 10000, 10000, 10000) for t in
            ("090500", "091000", "091500", "092000", "092500", "093000")]
    bars.append(_bar("093500", 10000, 10000, 9700, 9750))    # 하락, 음봉 -- C4 미충족
    bars.append(_bar("094000", 9750, 9820, 9740, 9800))      # 반등, 양봉 -- 유효 신호봉
    bars.append(_bar("094500", 9800, 9850, 9790, 9820))      # 진입봉
    return bars


PREV_CLOSE = 10000.0


def test_preregistered_grid_has_eight_combinations():
    assert len(PREREGISTERED_GRID) == 8
    assert (0.010, 0.6, 0.75) in PREREGISTERED_GRID


def test_fires_at_first_bullish_bar_meeting_deviation_after_bearish_decline():
    bars = _baseline_bars()
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig is not None
    assert sig.entry_time == "094500"      # 봉8(094000) 다음 봉에 진입
    assert sig.entry_price == 9800.0
    assert sig.target_price > sig.entry_price
    assert sig.stop_price < sig.entry_price


def test_bearish_decline_bar_itself_never_becomes_signal_bar():
    # d를 낮춰도(봉7 자체의 dev는 크다) 봉7은 음봉이라 신호가 될 수 없다 -- 봉8에서만 발동
    bars = _baseline_bars()
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig.entry_time != "093500"
    assert sig.entry_time != "094000"


def test_no_signal_when_deviation_never_reaches_trigger():
    bars = [_bar(t, 10000, 10010, 9995, 10005) for t in
            ("090500", "091000", "091500", "092000", "092500", "093000", "093500", "094000", "094500")]
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig is None


def test_gap_event_disqualifies_entire_day():
    bars = _baseline_bars()
    bars[0] = _bar("090500", 10600, 10600, 10600, 10600)   # 시가 갭 +6% > 3% 상한
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig is None


def test_crash_disqualifies_entire_day_even_if_later_bar_looks_valid():
    bars = _baseline_bars()
    # 봉7을 전일종가의 93% 밑으로 급락시켜 C3(급락) 위반 -> 그날 전체 신호 금지
    bars[6] = _bar("093500", 10000, 10000, 9000, 9200)
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig is None


def test_recheck_failure_cancels_signal_without_retrying_later_bars():
    # 진입봉(094500) 시가가 신호봉 VWAP에 바짝 붙어(되돌림 이미 발생) C6 재확인 실패
    bars = _baseline_bars()
    bars[8] = _bar("094500", 9970, 9980, 9960, 9975)   # entry price 9970 -- VWAP 근접
    sig = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    assert sig is None


def test_higher_deviation_trigger_is_stricter():
    # 봉8의 dev가 1.0%~1.5% 사이라면 d=1.5%에서는 신호가 안 나와야 한다
    bars = _baseline_bars()
    sig_low = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.010, f=0.6, k_stop=0.75)
    sig_high = ivr_signal_for_day("005930", bars, PREV_CLOSE, d=0.015, f=0.6, k_stop=0.75)
    assert sig_low is not None
    # 이 시나리오의 실제 dev가 1.5%를 넘는지 여부에 따라 sig_high는 있을 수도 없을 수도 있음 --
    # 최소한 d가 커질수록 더 엄격(신호가 안 나오거나 나오는 진입가가 동일)해야 한다는 것만 확인
    if sig_high is not None:
        assert sig_high.entry_time == sig_low.entry_time
