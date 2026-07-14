"""리스크 기반 포지션 사이징 (AlgoLab 블로그 리서치 반영, 2026-07-15).

배경: `phase0.engine.core.exposure()`/`daily_account()`는 "슬롯당 고정
비중"만 다뤄 손절 거리를 반영하지 않는다 — 표준 1~2% 룰(포지션 크기 =
자본 x 리스크% / (진입가-손절가))이 빠져 있었다. 이 모듈은 그 공식을
`phase0.backtest.g0_backtester.Signal` 계약(entry_price, stop_price가
이미 있음) 위에 얹는다. 전략이 산출한 신호를 실제 주문 수량으로 바꾸는
마지막 단계이며, core.py의 기대값 계산과는 독립적이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from phase0.backtest.g0_backtester import Signal

DEFAULT_RISK_PCT = 0.01   # 거래당 허용 손실 상한(자본 대비) — 표준 1~2% 룰의 하단


@dataclass
class PositionSize:
    shares: int
    risked_krw: float     # 손절 도달 시 실제 손실액(수량 x 손절폭)
    notional_krw: float   # 진입 시 투입 금액(수량 x 진입가)


def size_by_risk(capital_krw: float, signal: Signal, risk_pct: float = DEFAULT_RISK_PCT) -> PositionSize:
    """포지션 크기 = (자본 x 리스크%) / (진입가 - 손절가), 소수점 이하는 버림(보수화).

    손절가가 진입가 이상이면(설계 오류) ValueError. 리스크 예산이 1주 손절폭보다
    작으면(자본이 너무 작거나 손절이 너무 넓으면) shares=0을 반환한다 — 예외가
    아니라 "이 자본으로는 이 거래를 못 한다"는 유효한 결과다.
    """
    per_share_risk = signal.entry_price - signal.stop_price
    if per_share_risk <= 0:
        raise ValueError(
            f"손절가({signal.stop_price})가 진입가({signal.entry_price})보다 낮아야 합니다"
        )
    risk_budget = capital_krw * risk_pct
    shares = int(risk_budget // per_share_risk)
    return PositionSize(
        shares=shares,
        risked_krw=shares * per_share_risk,
        notional_krw=shares * signal.entry_price,
    )


def portfolio_risk_ok(
    position_sizes: Sequence[PositionSize], capital_krw: float, max_portfolio_risk_pct: float = 0.05
) -> bool:
    """동시 보유 포지션 전체의 합산 리스크가 계좌 한도(기본 5%) 이내인지 확인."""
    total_risk = sum(p.risked_krw for p in position_sizes)
    return total_risk <= capital_krw * max_portfolio_risk_pct
