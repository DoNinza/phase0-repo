"""손실 대응 서킷브레이커 — 사전 커밋 정책 (AlgoLab 블로그 리서치, 2026-07-15).

핵심 원칙(트레이딩 심리 가이드 리서치): "결정은 손실을 보기 전에 고요할 때
정하고, 폭풍 속에서는 실행만 한다." 아직 실전 배치 전인 지금 임계값을
코드로 못박아 둔다 — 손실회피·최근성 편향으로 실시간에 판단을 바꾸는 것을
막기 위함이다. 아래 기본값은 블로그 리서치에서 참고한 예시 수치이며,
실제 배치 전에 감내 가능한 손실 수준에 맞춰 재조정해야 한다(파라미터화
되어 있음) — 다만 그 조정도 "고요할 때" 미리 해야 하며 실행 중 즉흥적으로
바꾸지 않는다는 게 핵심이다.

주의: 이 모듈은 신호 생성/백테스트와 무관하다 — 실거래 운영 단계에서
계좌 상태를 넣으면 "지금 신규 진입을 멈춰야 하는가"를 결정하는 순수
함수만 제공한다. 실제 계좌 상태 추적(일간/주간/월간 수익률 누적, 연속
손실 카운트)은 아직 이 모듈 밖에 있다 — 실거래 배선은 이후 단계.

추가(2026-07-15, GitHub `SilentFleetKK/riskguard` 리서치 반영): 일간/
주간/월간 손실 한도는 전부 달력 경계에서 리셋된다는 맹점이 있다 — 예를
들어 월말에 -9%, 리셋 후 월초에 다시 -9%면 실제 고점 대비 낙폭은 -18%
지만 "월간 -10%" 어느 쪽도 단독으로는 안 걸린다. `max_drawdown_pct`는
달력 리셋이 없는 고점 대비 낙폭(peak-to-trough)을 별도로 잡아 이 맹점을
메운다 — riskguard의 기본값(15%)을 그대로 승계했다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HaltReason(Enum):
    NONE = "none"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    MONTHLY_LOSS_LIMIT = "monthly_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    POST_CRASH_COOLDOWN = "post_crash_cooldown"


@dataclass
class CircuitBreakerConfig:
    daily_loss_limit: float = -0.02        # 일일 손실 -2% 도달 시 당일 신규 진입 중지
    weekly_loss_limit: float = -0.05       # 주간 손실 -5% 도달 시 해당 주 신규 진입 중지
    monthly_loss_limit: float = -0.10      # 월간 손실 -10% 도달 시 1주일 강제 휴식
    max_drawdown_pct: float = -0.15        # 고점 대비 낙폭 한도(달력 리셋 없음, riskguard 기본값 승계)
    max_consecutive_losses: int = 8        # 예시값 — 전략별 "과거 정상 범위"로 재조정 필요
    market_crash_threshold: float = -0.05  # 시장(코스피) 일간 급락 기준
    cooldown_hours_after_crash: int = 48   # 시장 급락 후 냉각 기간


def check_halt(
    daily_return: float,
    weekly_return: float,
    monthly_return: float,
    consecutive_losses: int,
    hours_since_market_crash: float | None,
    current_drawdown_pct: float = 0.0,
    config: CircuitBreakerConfig = CircuitBreakerConfig(),
) -> HaltReason:
    """신규 진입을 멈춰야 하는지 판정.

    우선순위: 냉각기간 > 낙폭한도 > 월간 > 주간 > 일간 > 연속손실. 낙폭한도를
    달력 기준 한도들보다 먼저 보는 이유: 달력 경계 리셋이 없어 그 맹점을
    독립적으로 잡아내는 역할이기 때문.

    hours_since_market_crash: 가장 최근 시장 급락 이후 경과 시간(시간 단위).
    급락이 아예 없었으면 None.
    current_drawdown_pct: 고점 대비 현재 낙폭(0 이하 소수, 예: -0.12 = -12%).
    """
    if hours_since_market_crash is not None and hours_since_market_crash < config.cooldown_hours_after_crash:
        return HaltReason.POST_CRASH_COOLDOWN
    if current_drawdown_pct <= config.max_drawdown_pct:
        return HaltReason.DRAWDOWN_LIMIT
    if monthly_return <= config.monthly_loss_limit:
        return HaltReason.MONTHLY_LOSS_LIMIT
    if weekly_return <= config.weekly_loss_limit:
        return HaltReason.WEEKLY_LOSS_LIMIT
    if daily_return <= config.daily_loss_limit:
        return HaltReason.DAILY_LOSS_LIMIT
    if consecutive_losses >= config.max_consecutive_losses:
        return HaltReason.CONSECUTIVE_LOSSES
    return HaltReason.NONE
