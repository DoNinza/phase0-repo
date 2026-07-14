"""표 생성 스모크 테스트 — costs.yaml과 연동했을 때도 원본 문서 수치가 재현되는지 확인.

STAGE 3 원칙("표는 엔진 출력의 전재")을 실제로 지키고 있는지를 코드로 고정한다.
"""

from phase0.config.costs import base_breakdown, scenario_costs
from phase0.engine import tables


def test_t_r01_verify_contains_expected_values():
    out = tables.t_r01_verify()
    assert "4.500%" in out
    assert "3.571%" in out
    assert "3.375%" in out


def test_t_breakeven_uses_injected_cost():
    bd = base_breakdown()
    out = tables.t_breakeven(bd.base_total)
    # W=1.5%, L=0.8% 조합 — 2026-07-14 실측 비용(C=0.3854%) 반영 후 51.5%
    # (문서 원본의 50.4%는 C=0.36% 플레이스홀더 기준값)
    assert "51.5%" in out


def test_t_cost_sens_matches_document_row_for_base_2026():
    scenarios = scenario_costs()
    out = tables.t_cost_sens(scenarios)
    # 2026-07-14: 위탁수수료·유관기관제비용 실측 반영 후 Base=0.3854%,
    # E_trade(p=55%,W=1.5%,L=0.9%)는 문서 원본의 +0.060%에서 +0.035%로 하향.
    assert "+0.035%" in out  # Base 2026 행
    assert "-0.081%" in out  # Conservative(1.3x) 행 — 원본 -0.048%에서 하향


def test_t_annual_matches_document_64pct_row():
    out = tables.t_annual()
    assert "**6.4%**" in out


def test_t_target_matches_document():
    bd = base_breakdown()
    out = tables.t_target(bd.base_total)
    # 2026-07-14 실측 비용(C=0.3854%) 반영 후 4.64% (문서 원본은 C=0.36% 기준 4.60%)
    assert "4.64%" in out  # 일1%, 노출0.625, p=60%


def test_t_wf_matches_document_3_segments():
    out = tables.t_wf()
    assert "**3개**" in out


def test_t_streak_matches_document():
    bd = base_breakdown()
    out = tables.t_streak(bd.base_total)
    assert "8연속" in out
