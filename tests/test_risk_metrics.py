import math

import pytest

from phase0.paper.trade_log import PaperEntry
from phase0.risk.metrics import daily_pnl_series, historical_var, sharpe_ratio, sortino_ratio


def _entry(date, pnl_pct, ticker="005930"):
    return PaperEntry(ticker=ticker, date=date, entry_price=100.0, target_price=105.0,
                       stop_price=97.0, shares=10, resolution="target_hit", pnl_pct=pnl_pct)


def test_daily_pnl_series_averages_same_day_trades():
    entries = [_entry("20260701", 0.02, "A"), _entry("20260701", -0.01, "B"), _entry("20260702", 0.03, "C")]
    series = daily_pnl_series(entries)
    assert series == [("20260701", 0.005), ("20260702", 0.03)]


def test_daily_pnl_series_ignores_unresolved():
    entries = [_entry("20260701", None), _entry("20260701", 0.01)]
    assert daily_pnl_series(entries) == [("20260701", 0.01)]


def test_daily_pnl_series_sorted_by_date():
    entries = [_entry("20260702", 0.01), _entry("20260701", 0.02)]
    assert [d for d, _ in daily_pnl_series(entries)] == ["20260701", "20260702"]


def test_sharpe_none_below_min_sample():
    assert sharpe_ratio([0.01] * 19) is None


def test_sharpe_computed_above_min_sample():
    returns = [0.01, -0.005] * 10  # n=20
    result = sharpe_ratio(returns)
    assert result is not None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    expected = (mean / math.sqrt(variance)) * math.sqrt(252)
    assert result == pytest.approx(expected)


def test_sharpe_none_when_zero_variance():
    assert sharpe_ratio([0.01] * 25) is None


def test_sortino_none_below_min_sample():
    assert sortino_ratio([0.01] * 19) is None


def test_sortino_computed_above_min_sample():
    returns = [0.02] * 15 + [-0.01] * 5   # n=20, has downside
    result = sortino_ratio(returns)
    assert result is not None
    assert result > 0   # 평균 수익률이 양수이므로


def test_sortino_none_when_no_downside():
    # 전부 양수(하방편차=0)면 계산 불가로 None
    assert sortino_ratio([0.01] * 25) is None


def test_historical_var_none_below_min_sample():
    assert historical_var([0.01] * 29) is None


def test_historical_var_returns_lower_tail_value():
    returns = list(range(-15, 15))   # n=30, sorted -15..14
    returns = [r / 1000 for r in returns]
    result = historical_var(returns, confidence=0.95)
    ordered = sorted(returns)
    expected = ordered[int(0.05 * 30)]
    assert result == pytest.approx(expected)
