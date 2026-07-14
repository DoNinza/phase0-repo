import pytest

from phase0.config.costs import base_breakdown, scenario_costs, conditional_value


def test_base_total_matches_realized_0385pct():
    # 2026-07-14: 위탁수수료(사용자 실계좌 BanKIS 0.0140527%/편도)·유관기관제비용
    # 실측 반영 후 Base = 0.36% → 0.3854%로 갱신(기획안 문서의 0.36%는 플레이스홀더였음).
    bd = base_breakdown()
    assert round(bd.base_total * 100, 4) == 0.3854


def test_all_components_resolved_phase0_blocker_cleared():
    # 위탁수수료·유관기관제비용이 모두 실측되어 Phase 0 Blocker(§5.6)가 해소됨.
    bd = base_breakdown()
    assert bd.unresolved == []


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
    assert bd.base_total == pytest.approx(0.003854054, abs=1e-9)
