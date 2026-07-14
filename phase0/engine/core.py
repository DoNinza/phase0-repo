"""Phase 0 계산 엔진 v1.1 — 단일 진실 공급원(Single Source of Truth)

원본: phase0_engine.py (v1.0). 수식·수치는 그대로 유지하고 패키지 구조로만 재편했다.
자가 점검(self_test)의 항등식 5건·경계값 3건은 tests/test_core.py 로 이관되어
CI에서 매 커밋마다 자동 실행된다 (원본의 '단위 테스트 통과 없이는 표를 출력하지
않는다'는 원칙을 CI 게이트로 승격).

단위 규약: 함수 인터페이스는 전부 '소수'(0.01 = 1%). 표시 계층에서만 %로 변환.
"""

from __future__ import annotations

# ---------- 핵심 수식 ----------

def e_trade(p: float, W: float, L: float, C: float) -> float:
    """거래당 기대값(소수).

    Args:
        p: 승률 (0~1)
        W: 평균이익 (소수, 승리 거래 기준)
        L: 평균손실 절댓값 (소수, 패배 거래 기준)
        C: 왕복비용 (소수)
    """
    return p * W - (1 - p) * L - C


def breakeven_p(W: float, L: float, C: float) -> float:
    """E_trade = 0 이 되는 손익분기 승률."""
    return (L + C) / (W + L)


def req_p(E: float, W: float, L: float, C: float) -> float:
    """목표 기대값 E를 달성하기 위해 필요한 승률."""
    return (E + L + C) / (W + L)


def req_W(E: float, p: float, L: float, C: float) -> float:
    """목표 기대값 E를 달성하기 위해 필요한 평균이익."""
    return (E + (1 - p) * L + C) / p


def exposure(slots: int, weight: float, trig: float) -> float:
    """전체 거래일 기준 평균 노출도.

    방식 A: trig(발동률)가 전체 거래일 기준이면 무거래일의 0 기여가 이미
    포함되어 있으므로, 매매일 비율을 추가로 곱하지 않는다 (기획안 R-03,
    participation 파라미터는 폐기됨 — 중복 차감 금지).
    """
    return slots * weight * trig


def daily_account(expo: float, E: float) -> float:
    """계좌 기준 일 기대 수익 (%p 단위는 표시 계층에서 처리)."""
    return expo * E


def annualize(daily: float, days: int = 248) -> float:
    """방식 A 노출도 기준 연복리.

    participation 추가 곱은 이중 차감이므로 금지 (R-03).
    """
    return (1 + daily) ** days - 1


# ---------- 표시 계층 헬퍼 ----------

def to_pct(x: float, decimals: int = 2) -> str:
    """소수 -> 퍼센트 문자열. 계산에는 절대 쓰지 않고 출력 전용."""
    return f"{x * 100:.{decimals}f}%"
