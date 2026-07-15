from phase0.risk.circuit_breaker import CircuitBreakerConfig, HaltReason, check_halt


def _ok(**overrides):
    base = dict(daily_return=0.0, weekly_return=0.0, monthly_return=0.0,
                consecutive_losses=0, hours_since_market_crash=None)
    base.update(overrides)
    return base


def test_no_halt_when_all_metrics_within_normal_range():
    assert check_halt(**_ok()) == HaltReason.NONE


def test_halts_on_daily_loss_limit():
    assert check_halt(**_ok(daily_return=-0.021)) == HaltReason.DAILY_LOSS_LIMIT


def test_halts_on_weekly_loss_limit():
    assert check_halt(**_ok(weekly_return=-0.051)) == HaltReason.WEEKLY_LOSS_LIMIT


def test_halts_on_monthly_loss_limit():
    assert check_halt(**_ok(monthly_return=-0.101)) == HaltReason.MONTHLY_LOSS_LIMIT


def test_halts_on_consecutive_losses():
    assert check_halt(**_ok(consecutive_losses=8)) == HaltReason.CONSECUTIVE_LOSSES


def test_no_halt_just_below_consecutive_loss_threshold():
    assert check_halt(**_ok(consecutive_losses=7)) == HaltReason.NONE


def test_halts_during_post_crash_cooldown():
    assert check_halt(**_ok(hours_since_market_crash=10)) == HaltReason.POST_CRASH_COOLDOWN


def test_no_halt_after_cooldown_window_passes():
    assert check_halt(**_ok(hours_since_market_crash=49)) == HaltReason.NONE


def test_cooldown_takes_priority_over_other_breaches():
    # 냉각기간 중이면 다른 지표가 동시에 나빠도 냉각 사유가 우선 보고된다
    assert check_halt(**_ok(hours_since_market_crash=1, monthly_return=-0.2)) == HaltReason.POST_CRASH_COOLDOWN


def test_monthly_takes_priority_over_daily_and_weekly():
    assert check_halt(**_ok(daily_return=-0.03, weekly_return=-0.06, monthly_return=-0.11)) == HaltReason.MONTHLY_LOSS_LIMIT


def test_custom_config_thresholds_are_respected():
    config = CircuitBreakerConfig(daily_loss_limit=-0.01)
    assert check_halt(**_ok(daily_return=-0.015), config=config) == HaltReason.DAILY_LOSS_LIMIT
    assert check_halt(**_ok(daily_return=-0.005), config=config) == HaltReason.NONE


def test_halts_on_drawdown_limit():
    assert check_halt(**_ok(), current_drawdown_pct=-0.151) == HaltReason.DRAWDOWN_LIMIT


def test_no_halt_just_above_drawdown_threshold():
    assert check_halt(**_ok(), current_drawdown_pct=-0.149) == HaltReason.NONE


def test_drawdown_catches_what_calendar_resets_miss():
    # 월간 -9%씩 두 달 연속 -> 어느 쪽도 월간 한도(-10%) 단독으로는 안 걸리지만
    # 리셋 없는 고점 대비 낙폭은 누적돼 -15% 한도에 걸린다.
    assert check_halt(**_ok(monthly_return=-0.09), current_drawdown_pct=-0.18) == HaltReason.DRAWDOWN_LIMIT


def test_drawdown_takes_priority_over_monthly_but_not_cooldown():
    assert check_halt(**_ok(monthly_return=-0.20), current_drawdown_pct=-0.20) == HaltReason.DRAWDOWN_LIMIT
    assert check_halt(**_ok(hours_since_market_crash=1, monthly_return=-0.20),
                       current_drawdown_pct=-0.20) == HaltReason.POST_CRASH_COOLDOWN
