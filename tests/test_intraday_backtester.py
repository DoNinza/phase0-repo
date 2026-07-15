from phase0.backtest.intraday_backtester import (
    IntradayResolution, IntradaySignal, resolve_intraday_trade,
)
from phase0.data.minute_bar_store import MinuteBar


def _bar(time, o, h, l, c, v=1000):
    return MinuteBar(date="20260715", time=time, open=o, high=h, low=l, close=c, volume=v)


def _sig(entry_time="093000", entry_price=10000.0, target_price=10200.0, stop_price=9900.0):
    return IntradaySignal(
        ticker="005930", date="20260715", entry_time=entry_time,
        entry_price=entry_price, target_price=target_price, stop_price=stop_price,
    )


def test_resolves_target_hit_before_stop():
    bars = [
        _bar("093000", 10000, 10050, 9950, 10000),   # 진입봉, 미도달
        _bar("093500", 10000, 10250, 9950, 10200),   # 목표가 도달
        _bar("094000", 10200, 10300, 9800, 10000),   # 이후 봉(무시돼야 함)
    ]
    result = resolve_intraday_trade(bars, _sig(), forced_exit_time="151500")
    assert result.resolution == IntradayResolution.TARGET_HIT
    assert result.pnl_pct > 0
    assert result.is_win


def test_resolves_stop_hit_before_target():
    bars = [
        _bar("093000", 10000, 10050, 9950, 10000),
        _bar("093500", 10000, 10050, 9850, 9900),    # 손절가 도달
        _bar("094000", 9900, 10300, 9800, 10000),
    ]
    result = resolve_intraday_trade(bars, _sig(), forced_exit_time="151500")
    assert result.resolution == IntradayResolution.STOP_HIT
    assert not result.is_win


def test_same_bar_dual_touch_resolves_as_stop_conservatively():
    bars = [
        _bar("093000", 10000, 10250, 9850, 10000),   # 목표·손절 둘 다 도달
    ]
    result = resolve_intraday_trade(bars, _sig(), forced_exit_time="151500")
    assert result.resolution == IntradayResolution.STOP_HIT


def test_time_exit_when_neither_hit_by_forced_exit():
    bars = [
        _bar("093000", 10000, 10050, 9950, 10000),
        _bar("151500", 10050, 10100, 10000, 10050),   # 강제청산 봉, 목표·손절 미도달
    ]
    result = resolve_intraday_trade(bars, _sig(), forced_exit_time="151500")
    assert result.resolution == IntradayResolution.TIME_EXIT
    assert result.pnl_pct == (10050 - 10000) / 10000


def test_bars_after_forced_exit_time_are_ignored():
    bars = [
        _bar("093000", 10000, 10050, 9950, 10000),
        _bar("151500", 10050, 10100, 10000, 10050),
        _bar("152000", 10050, 10500, 9000, 10400),   # 이후 폭등 -- 무시돼야 함
    ]
    result = resolve_intraday_trade(bars, _sig(), forced_exit_time="151500")
    assert result.resolution == IntradayResolution.TIME_EXIT
    assert result.pnl_pct == (10050 - 10000) / 10000
