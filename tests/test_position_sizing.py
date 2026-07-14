import pytest

from phase0.backtest.g0_backtester import Signal
from phase0.engine.position_sizing import PositionSize, portfolio_risk_ok, size_by_risk


def _signal(entry=10000.0, target=10500.0, stop=9800.0):
    return Signal(date="D01", entry_price=entry, target_price=target, stop_price=stop)


def test_size_by_risk_computes_shares_from_risk_budget():
    # 자본 1000만원, 리스크 1% = 10만원 예산, 1주 손절폭 = 200원 -> 500주
    sig = _signal(entry=10000.0, stop=9800.0)
    size = size_by_risk(10_000_000, sig, risk_pct=0.01)
    assert size.shares == 500
    assert size.risked_krw == pytest.approx(500 * 200.0)
    assert size.notional_krw == pytest.approx(500 * 10000.0)


def test_size_by_risk_floors_shares_conservatively():
    # 예산 100_000 / 손절폭 300 = 333.33 -> 333주로 버림(더 적게)
    sig = _signal(entry=10000.0, stop=9700.0)
    size = size_by_risk(10_000_000, sig, risk_pct=0.01)
    assert size.shares == 333


def test_size_by_risk_returns_zero_shares_when_capital_too_small():
    sig = _signal(entry=10000.0, stop=9800.0)   # 1주 손절폭 200원
    size = size_by_risk(100.0, sig, risk_pct=0.01)   # 예산 1원 < 200원
    assert size.shares == 0
    assert size.risked_krw == 0
    assert size.notional_krw == 0


def test_size_by_risk_raises_when_stop_not_below_entry():
    sig = _signal(entry=10000.0, stop=10000.0)
    with pytest.raises(ValueError):
        size_by_risk(10_000_000, sig)


def test_portfolio_risk_ok_within_limit():
    sizes = [PositionSize(shares=1, risked_krw=200_000, notional_krw=1_000_000),
              PositionSize(shares=1, risked_krw=200_000, notional_krw=1_000_000)]
    # 합산 리스크 400_000 / 자본 10_000_000 = 4% <= 기본 5% 한도
    assert portfolio_risk_ok(sizes, 10_000_000) is True


def test_portfolio_risk_ok_exceeds_limit():
    sizes = [PositionSize(shares=1, risked_krw=300_000, notional_krw=1_000_000),
              PositionSize(shares=1, risked_krw=300_000, notional_krw=1_000_000)]
    # 합산 리스크 600_000 / 자본 10_000_000 = 6% > 기본 5% 한도
    assert portfolio_risk_ok(sizes, 10_000_000) is False
