"""위험지표(Sharpe/Sortino/역사적 VaR) — 표본 부족 시 정직하게 결측 반환 (2026-07-16).

배경: 이 프로젝트는 표본이 작을 때 확정적인 숫자를 내지 않는다는 원칙을
지켜왔다(IVR 표본문턱 사례, README 참고). Sharpe/Sortino/VaR는 표본이
작을수록 극단값이 나오기 쉬운 지표라 최소 표본 문턱 미달 시 그 이유와
함께 결측(None)을 반환한다 — 대시보드는 이걸 "표본부족 n=X"로 정직하게
표시해야 하며, 절대 문턱 미달 값을 그대로 보여주면 안 된다.

daily_pnl_series는 phase0.paper.trade_log.daily_return과 동일하게 "그날
청산된 거래들의 pnl_pct 단순평균"을 하루 단위 수익률 근사치로 쓴다 —
자본 복리·동시보유를 반영한 진짜 계좌 수익률이 아니라는 한계는
trade_log.py 문서화와 동일하다.
"""

from __future__ import annotations

import math
from typing import Sequence

from phase0.paper.trade_log import PaperEntry

MIN_DAYS_FOR_RATIO = 20     # Sharpe/Sortino 최소 거래일수
MIN_DAYS_FOR_VAR = 30       # 95% VaR 최소 거래일수(5% 분위 추정 여유)
TRADING_DAYS_PER_YEAR = 252


def daily_pnl_series(entries: Sequence[PaperEntry]) -> list[tuple[str, float]]:
    """(날짜, 그날 청산 거래 pnl_pct 단순평균) 목록, 날짜순 정렬."""
    by_date: dict[str, list[float]] = {}
    for e in entries:
        if e.pnl_pct is None:
            continue
        by_date.setdefault(e.date, []).append(e.pnl_pct)
    return [(d, sum(v) / len(v)) for d, v in sorted(by_date.items())]


def sharpe_ratio(daily_returns: Sequence[float]) -> float | None:
    """연율화 Sharpe(무위험수익률=0 가정) — n<MIN_DAYS_FOR_RATIO면 None."""
    n = len(daily_returns)
    if n < MIN_DAYS_FOR_RATIO:
        return None
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(daily_returns: Sequence[float]) -> float | None:
    """연율화 Sortino(하방편차 기준) — n<MIN_DAYS_FOR_RATIO면 None."""
    n = len(daily_returns)
    if n < MIN_DAYS_FOR_RATIO:
        return None
    mean = sum(daily_returns) / n
    downside_sq = [min(r, 0.0) ** 2 for r in daily_returns]
    downside_dev = math.sqrt(sum(downside_sq) / n)
    if downside_dev == 0:
        return None
    return (mean / downside_dev) * math.sqrt(TRADING_DAYS_PER_YEAR)


def historical_var(daily_returns: Sequence[float], confidence: float = 0.95) -> float | None:
    """역사적 VaR — 하위 (1-confidence) 분위수(손실 쪽 소수, 예: -0.032=-3.2%).

    n<MIN_DAYS_FOR_VAR면 None(분위수 추정 자체가 신뢰할 수 없는 표본크기).
    """
    n = len(daily_returns)
    if n < MIN_DAYS_FOR_VAR:
        return None
    ordered = sorted(daily_returns)
    idx = max(0, min(n - 1, int((1 - confidence) * n)))
    return ordered[idx]
