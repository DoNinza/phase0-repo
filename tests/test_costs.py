import pytest

from phase0.config.costs import base_breakdown, scenario_costs, conditional_value


def test_base_total_matches_document_036pct():
    bd = base_breakdown()
    assert round(bd.base_total * 100, 2) == 0.36


def test_unresolved_flags_brokerage_and_exchange_fee():
    bd = base_breakdown()
    assert "brokerage_commission_roundtrip" in bd.unresolved


def test_scenario_costs_conservative_is_13x_base():
    bd = base_breakdown()
    scenarios = dict(scenario_costs())
    conservative = scenarios["Conservative(1.3x)"]
    assert conservative == pytest.approx(bd.base_total * 1.3, abs=1e-9)


def test_scenario_costs_stress_is_2x_base():
    bd = base_breakdown()
    scenarios = dict(scenario_costs())
    stress = scenarios["Stress(2x)"]
    assert stress == pytest.approx(bd.base_total * 2.0, abs=1e-9)


def test_optimistic_is_override_not_multiplier():
    scenarios = dict(scenario_costs())
    assert scenarios["Optimistic(참고용, 판정 사용 금지)"] == pytest.approx(0.0028, abs=1e-9)


def test_conditional_stoploss_extra_excluded_from_base():
    bd = base_breakdown()
    extra = conditional_value("stoploss_market_extra")
    assert extra == pytest.approx(0.0010, abs=1e-9)
    # base_total은 이 항목을 포함하지 않아야 한다 (표8 전용 가산)
    assert bd.base_total == pytest.approx(0.0036, abs=1e-9)
