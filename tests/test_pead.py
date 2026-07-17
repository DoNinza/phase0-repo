"""PEAD 전략 Phase 2 사전등록 상수 검증 (phase0/strategy/pead.py).

Phase 2 시점엔 신호 함수가 아직 없다(기획안 §8 로드맵 — 그건 Phase 3).
여기선 사전등록된 격자·상수가 기획안 §5/§10과 정확히 일치하는지만
검증한다 — 이 값들은 백테스트 결과를 보기 전에 확정됐으므로, 앞으로
바뀌면 안 된다는 걸 테스트로 고정한다.
"""

from phase0.strategy.pead import (
    EX_DIV_WINDOW,
    H_GRID,
    K_STOP_GRID,
    LONG_ONLY,
    MIN_DISTINCT_DATES,
    MIN_EVENTS,
    PREREGISTERED_GRID,
    SUE_DENOMINATOR,
    THETA_GRID,
)


def test_preregistered_grid_has_eight_combinations():
    assert len(PREREGISTERED_GRID) == 8
    assert (0.03, 5, 1.5) in PREREGISTERED_GRID
    assert (0.10, 20, 2.5) in PREREGISTERED_GRID


def test_grid_is_full_cartesian_product():
    expected = {
        (theta, h, k) for theta in THETA_GRID for h in H_GRID for k in K_STOP_GRID
    }
    assert set(PREREGISTERED_GRID) == expected


def test_sue_denominator_is_sales():
    assert SUE_DENOMINATOR == "sales"


def test_theta_grid_values():
    assert THETA_GRID == (0.03, 0.10)


def test_h_grid_values():
    assert H_GRID == (5, 20)


def test_k_stop_grid_values():
    assert K_STOP_GRID == (1.5, 2.5)


def test_ex_div_window_matches_gdr_c5():
    from phase0.strategy.gap_rebound import EX_DIV_WINDOW as GDR_EX_DIV_WINDOW

    assert EX_DIV_WINDOW == GDR_EX_DIV_WINDOW == ("1222", "1231")


def test_long_only():
    assert LONG_ONLY is True


def test_min_sample_thresholds():
    assert MIN_EVENTS == 300
    assert MIN_DISTINCT_DATES == 150
