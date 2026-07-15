import pytest

from phase0.paper.trade_log import (
    PaperEntry, append_entry, consecutive_losses, current_drawdown, daily_return,
    load_entries, monthly_return, rewrite_all, weekly_return,
)


def _entry(ticker="005930", date="20260713", pnl_pct=None, resolution=None):
    return PaperEntry(
        ticker=ticker, date=date, entry_price=10000.0, target_price=10500.0,
        stop_price=9800.0, shares=100, resolution=resolution, pnl_pct=pnl_pct,
    )


def test_append_and_load_roundtrip(tmp_path):
    log_path = tmp_path / "trades.jsonl"
    e1 = _entry(date="20260713", pnl_pct=0.02, resolution="target_hit")
    e2 = _entry(date="20260714", pnl_pct=-0.01, resolution="stop_hit")

    append_entry(log_path, e1)
    append_entry(log_path, e2)

    loaded = load_entries(log_path)
    assert len(loaded) == 2
    assert loaded[0] == e1
    assert loaded[1] == e2


def test_load_entries_returns_empty_list_when_file_missing(tmp_path):
    assert load_entries(tmp_path / "does_not_exist.jsonl") == []


def test_rewrite_all_replaces_file_contents(tmp_path):
    log_path = tmp_path / "trades.jsonl"
    append_entry(log_path, _entry(date="20260713"))
    rewrite_all(log_path, [_entry(date="20260714", pnl_pct=0.01, resolution="target_hit")])

    loaded = load_entries(log_path)
    assert len(loaded) == 1
    assert loaded[0].date == "20260714"


def test_unresolved_entries_are_excluded_from_period_returns():
    entries = [
        _entry(date="20260713", pnl_pct=None, resolution=None),   # 미결 - 제외돼야 함
        _entry(date="20260713", pnl_pct=0.02, resolution="target_hit"),
    ]
    assert daily_return(entries, "20260713") == 0.02


def test_daily_return_averages_same_day_trades():
    entries = [
        _entry(date="20260713", pnl_pct=0.02, resolution="target_hit"),
        _entry(date="20260713", pnl_pct=-0.04, resolution="stop_hit"),
    ]
    assert daily_return(entries, "20260713") == -0.01


def test_daily_return_zero_when_no_trades_that_day():
    assert daily_return([_entry(date="20260713", pnl_pct=0.02, resolution="target_hit")], "20260714") == 0.0


def test_weekly_return_includes_only_same_week():
    # 2026-07-13(월)~2026-07-17(금)이 한 주. 07-13과 07-11(전주 토요일)은 다른 주.
    entries = [
        _entry(date="20260711", pnl_pct=0.10, resolution="target_hit"),   # 전주 토요일 - 제외
        _entry(date="20260713", pnl_pct=0.02, resolution="target_hit"),   # 이번주 월
        _entry(date="20260716", pnl_pct=-0.02, resolution="stop_hit"),    # 이번주 목
    ]
    assert weekly_return(entries, "20260716") == 0.0   # (0.02 + -0.02)/2


def test_monthly_return_includes_only_same_month_up_to_date():
    entries = [
        _entry(date="20260630", pnl_pct=0.50, resolution="target_hit"),   # 전월 - 제외
        _entry(date="20260701", pnl_pct=0.01, resolution="target_hit"),
        _entry(date="20260715", pnl_pct=-0.03, resolution="stop_hit"),
        _entry(date="20260720", pnl_pct=0.99, resolution="target_hit"),   # as_of 이후 - 제외
    ]
    assert monthly_return(entries, "20260715") == (0.01 - 0.03) / 2


def test_consecutive_losses_counts_from_most_recent():
    entries = [
        _entry(date="20260710", pnl_pct=0.01, resolution="target_hit"),
        _entry(date="20260711", pnl_pct=-0.01, resolution="stop_hit"),
        _entry(date="20260712", pnl_pct=-0.02, resolution="stop_hit"),
        _entry(date="20260713", pnl_pct=-0.01, resolution="stop_hit"),
    ]
    assert consecutive_losses(entries) == 3


def test_consecutive_losses_resets_after_a_win():
    entries = [
        _entry(date="20260710", pnl_pct=-0.01, resolution="stop_hit"),
        _entry(date="20260711", pnl_pct=0.01, resolution="target_hit"),
    ]
    assert consecutive_losses(entries) == 0


def test_consecutive_losses_ignores_unresolved_trailing_entries():
    entries = [
        _entry(date="20260710", pnl_pct=-0.01, resolution="stop_hit"),
        _entry(date="20260711", pnl_pct=None, resolution=None),
    ]
    assert consecutive_losses(entries) == 1


def test_current_drawdown_zero_when_only_gains():
    entries = [
        _entry(date="20260710", pnl_pct=0.01, resolution="target_hit"),
        _entry(date="20260711", pnl_pct=0.02, resolution="target_hit"),
    ]
    assert current_drawdown(entries) == 0.0


def test_current_drawdown_measures_peak_to_trough():
    # 누적: +0.05 -> 0.10(고점) -> 0.04(낙폭 -0.06) -> 0.07
    entries = [
        _entry(date="20260710", pnl_pct=0.05, resolution="target_hit"),
        _entry(date="20260711", pnl_pct=0.05, resolution="target_hit"),
        _entry(date="20260712", pnl_pct=-0.06, resolution="stop_hit"),
        _entry(date="20260713", pnl_pct=0.03, resolution="target_hit"),
    ]
    assert current_drawdown(entries) == pytest.approx(-0.06)


def test_current_drawdown_ignores_unresolved_entries():
    entries = [
        _entry(date="20260710", pnl_pct=0.05, resolution="target_hit"),
        _entry(date="20260711", pnl_pct=None, resolution=None),
    ]
    assert current_drawdown(entries) == 0.0
