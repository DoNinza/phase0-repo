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
    # W=1.5%, L=0.8% 조합의 문서상 값 50.4%
    assert "50.4%" in out


def test_t_cost_sens_matches_document_row_for_base_2026():
    scenarios = scenario_costs()
    out = tables.t_cost_sens(scenarios)
    assert "+0.060%" in out  # Base 2026 행
    # 주의: 원본 phase0_engine.py는 Conservative 비용을 0.47%로 하드코딩했는데,
    # 이는 Base(0.36%)×1.3=0.468%를 소수점 둘째자리에서 반올림한 값이다(0.468→0.47%).
    # 반올림된 "표시용" 값을 다시 계산 입력으로 쓰면 -0.050%가 나오지만, 반올림 없이
    # 1.3배를 그대로 계산하면 -0.048%가 나온다 — 원본의 미세한 반올림 누적 오차
    # (<0.002%p)이며, 이 리팩터는 정밀값(-0.048%)을 쓴다. (README 기록)
    assert "-0.048%" in out  # Conservative 행 (정밀 계산값, 원본 표기 -0.050%와 미세 차이)


def test_t_annual_matches_document_64pct_row():
    out = tables.t_annual()
    assert "**6.4%**" in out


def test_t_target_matches_document():
    bd = base_breakdown()
    out = tables.t_target(bd.base_total)
    assert "4.60%" in out  # 일1%, 노출0.625, p=60%


def test_t_wf_matches_document_3_segments():
    out = tables.t_wf()
    assert "**3개**" in out


def test_t_streak_matches_document():
    bd = base_breakdown()
    out = tables.t_streak(bd.base_total)
    assert "8연속" in out
