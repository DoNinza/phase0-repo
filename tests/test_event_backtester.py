from phase0.backtest.event_backtester import (
    EventResolution, EventSignal, resolve_event_trade, run_event_backtest,
)
from phase0.backtest.g0_backtester import DailyBar


def _bar(date, o, h, l, c):
    return DailyBar(date=date, open=o, high=h, low=l, close=c)


def _sig(entry_date="20260706", entry_price=10000.0, stop_price=9500.0, hold_days=5):
    return EventSignal(
        ticker="005930", entry_date=entry_date, entry_price=entry_price,
        stop_price=stop_price, hold_days=hold_days,
    )


def test_time_exit_when_stop_never_hit():
    bars = [
        _bar("20260706", 10000, 10100, 9950, 10050),  # 진입일
        _bar("20260707", 10050, 10200, 9900, 10150),
        _bar("20260708", 10150, 10250, 10000, 10200),
        _bar("20260709", 10200, 10300, 10100, 10250),
        _bar("20260710", 10250, 10350, 10150, 10300),
        _bar("20260713", 10300, 10400, 10200, 10350),  # 5거래일째, 시간청산
    ]
    result = resolve_event_trade(bars, _sig(hold_days=5))
    assert result.resolution == EventResolution.TIME_EXIT
    assert result.exit_date == "20260713"
    assert result.days_held == 5
    assert result.pnl_pct == (10350 - 10000) / 10000
    assert result.is_win


def test_stop_hit_on_entry_day_itself():
    bars = [
        _bar("20260706", 10000, 10050, 9400, 9800),  # 진입일 저가가 손절가 이하
        _bar("20260707", 9800, 9900, 9700, 9850),
    ]
    result = resolve_event_trade(bars, _sig(hold_days=1))
    assert result.resolution == EventResolution.STOP_HIT
    assert result.exit_date == "20260706"
    assert result.days_held == 0
    assert result.pnl_pct == (9500.0 - 10000.0) / 10000.0  # 손절가 그대로 체결(당일은 갭 불가)


def test_stop_hit_intraday_no_gap_uses_stop_price():
    bars = [
        _bar("20260706", 10000, 10100, 9950, 10050),  # 진입일, 미도달
        _bar("20260707", 10050, 10100, 9400, 9600),   # 시가는 손절가 위, 저가만 이하 — 갭 아님
    ]
    result = resolve_event_trade(bars, _sig(hold_days=1))
    assert result.resolution == EventResolution.STOP_HIT
    assert result.days_held == 1
    assert result.pnl_pct == (9500.0 - 10000.0) / 10000.0  # 손절가 그대로(불리하지 않은 쪽 아님)


def test_stop_hit_gap_down_fills_at_worse_open_price():
    bars = [
        _bar("20260706", 10000, 10100, 9950, 10050),  # 진입일, 미도달
        _bar("20260707", 9000, 9100, 8900, 9050),      # 시가부터 손절가 밑으로 갭
    ]
    result = resolve_event_trade(bars, _sig(hold_days=1))
    assert result.resolution == EventResolution.STOP_HIT
    assert result.days_held == 1
    assert result.pnl_pct == (9000.0 - 10000.0) / 10000.0  # 손절가(9500)가 아니라 더 나쁜 시가(9000)로 체결


def test_raises_when_not_enough_bars_for_hold_period():
    bars = [_bar("20260706", 10000, 10100, 9950, 10050)]
    try:
        resolve_event_trade(bars, _sig(hold_days=5))
        assert False, "should have raised"
    except ValueError:
        pass


def test_raises_when_first_bar_date_mismatches_entry_date():
    bars = [_bar("20260707", 10000, 10100, 9950, 10050)] * 6
    try:
        resolve_event_trade(bars, _sig(entry_date="20260706", hold_days=5))
        assert False, "should have raised"
    except ValueError:
        pass


def test_run_event_backtest_computes_e_net_and_trading_days():
    winning_trade_bars = [
        _bar("20260706", 10000, 10100, 9950, 10050),
        _bar("20260707", 10050, 10200, 9900, 10150),
        _bar("20260708", 10150, 10250, 10000, 10200),
        _bar("20260709", 10200, 10300, 10100, 10250),
        _bar("20260710", 10250, 10350, 10150, 10300),
        _bar("20260713", 10300, 10400, 10200, 10350),
    ]
    losing_trade_bars = [
        _bar("20260714", 10000, 10050, 9400, 9800),  # 진입일 손절(이후 봉은 무시됨)
        _bar("20260715", 9800, 9900, 9700, 9850),
        _bar("20260716", 9850, 9950, 9750, 9900),
        _bar("20260717", 9900, 10000, 9800, 9950),
        _bar("20260720", 9950, 10050, 9850, 10000),
        _bar("20260721", 10000, 10100, 9900, 10050),
    ]
    trades = [
        resolve_event_trade(winning_trade_bars, _sig(hold_days=5)),
        resolve_event_trade(losing_trade_bars, _sig(entry_date="20260714", hold_days=5)),
    ]
    verdict = run_event_backtest(trades, cost_base=0.003854)
    assert verdict.n_trades == 2
    assert verdict.n_trading_days == 2
    assert verdict.e_net == verdict.e_net  # NaN이 아님을 확인(자기 자신과 같음)
