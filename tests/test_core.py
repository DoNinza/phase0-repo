"""원본 phase0_engine.py self_test()의 항등식 5건·경계값 3건을 pytest로 이관.

CI에서 이 테스트가 실패하면 표(tables.py)를 생성/배포하지 않는다는 것이
기획안 STAGE 3의 '단위 테스트 통과 없이는 표를 출력하지 않는다' 원칙의
실제 게이트다.
"""

import math

import pytest

from phase0.engine.core import (
    e_trade, breakeven_p, req_p, req_W, exposure, daily_account, annualize,
)

EPS = 1e-9


# ---------- 항등식 5건 ----------

def test_identity_p1_equals_W_minus_C():
    assert e_trade(1, .03, .02, .003) == pytest.approx(.03 - .003, abs=EPS)


def test_identity_p0_equals_negL_minus_C():
    assert e_trade(0, .03, .02, .003) == pytest.approx(-.02 - .003, abs=EPS)


def test_identity_breakeven_gives_zero_expectation():
    p_star = breakeven_p(.015, .008, .003)
    assert e_trade(p_star, .015, .008, .003) == pytest.approx(0, abs=EPS)


def test_identity_reqp_zero_equals_breakeven():
    assert req_p(0, .015, .008, .003) == pytest.approx(breakeven_p(.015, .008, .003), abs=EPS)


def test_identity_reqW_roundtrip():
    W = req_W(.001, .55, .008, .003)
    assert e_trade(.55, W, .008, .003) == pytest.approx(.001, abs=EPS)


# ---------- 경계값 3건 ----------

def test_boundary_zero_cost_symmetric_WL_50pct():
    assert e_trade(.5, .02, .02, 0) == pytest.approx(0, abs=EPS)


def test_boundary_exposure_zero_and_full():
    assert exposure(5, .125, 0) == pytest.approx(0, abs=EPS)
    assert exposure(5, .2, 1) == pytest.approx(1.0, abs=EPS)


def test_boundary_annualize_zero_daily():
    assert annualize(0) == pytest.approx(0, abs=EPS)


# ---------- 문서 표1(R-01) 재현 검증 — 엔진 출력이 기획안 수치와 일치해야 함 ----------

@pytest.mark.parametrize("E,p,L,C,expected_pct", [
    (.016, .60, .02, .003, 4.500),
    (.016, .70, .02, .003, 3.571),
    (.020, .80, .02, .003, 3.375),
])
def test_r01_table_matches_document(E, p, L, C, expected_pct):
    W = req_W(E, p, L, C)
    assert W * 100 == pytest.approx(expected_pct, abs=0.001)


def test_daily_account_and_annualize_consistency():
    # 표5 두번째 행 재현: 발동률 40%, E=0.10% → 연 6.4%
    ex = exposure(5, .125, .40)
    d = daily_account(ex, .001)
    assert round(annualize(d) * 100, 1) == 6.4
