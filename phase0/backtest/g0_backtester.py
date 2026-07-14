"""G0 일봉 조기 기각 백테스터 — 낙관/보수 이중 경로 (기획안 §5.4, R-05).

배경: 하루봉만으로는 "고가가 목표가를 찍고, 저가도 손절가를 찍은" 날(충돌 봉)에
실제로 어느 것이 먼저 일어났는지 알 수 없다. v3는 이를 전부 손절로 처리(보수
가정)했는데, 이는 실제로는 진입도 안 됐을 케이스까지 손실로 계상하는 하향
편향을 만든다(거짓 음성 구조, R-05).

해소안: 같은 데이터에 대해 두 경로를 모두 계산한다.
  - 보수 경로: 충돌 봉 = 진입 → 손절 처리 (v3 승계)
  - 낙관 경로: 충돌 봉 = 손절 미발동, 진입가=목표가, 종가 청산

그리고 4분기 판정(§5.4):
  - 낙관 ≤ 0                     → 즉시 기각
  - 보수 > 0                     → G1 진행
  - 부호 갈림(낙관>0, 보수≤0)     → 유보 (분봉 표본으로 재판정 1회)
  - 충돌 봉 비중 > 40%            → "일봉 판정력 부족" 선언, 분봉 확보 전제 보류

원칙 유지: G0의 역할은 제거이지 채택이 아니다. 낙관 경로는 채택 근거로 쓰지
않는다 — 기각을 막기 위한 하한 점검 전용이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from phase0.engine.core import e_trade


@dataclass
class DailyBar:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class Signal:
    """전략이 그날 발동시킨 신호. target/stop은 절대 가격."""
    date: str
    entry_price: float
    target_price: float
    stop_price: float


class BarResolution(Enum):
    NO_ENTRY = "no_entry"           # 신호 없음/미충족
    TARGET_HIT = "target_hit"       # 손절 없이 목표가 도달
    STOP_HIT = "stop_hit"           # 목표가 없이 손절가 도달
    AMBIGUOUS = "ambiguous"         # 충돌 봉: 고가≥목표가 AND 저가≤손절가
    CLOSE_EXIT = "close_exit"       # 목표/손절 둘 다 미도달 → 종가 청산


@dataclass
class TradeResult:
    date: str
    resolution: BarResolution
    pnl_pct: float                  # 비용 미차감 손익률 (소수)

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0


def classify_bar(bar: DailyBar, sig: Signal) -> BarResolution:
    target_hit = bar.high >= sig.target_price
    stop_hit = bar.low <= sig.stop_price
    if target_hit and stop_hit:
        return BarResolution.AMBIGUOUS
    if target_hit:
        return BarResolution.TARGET_HIT
    if stop_hit:
        return BarResolution.STOP_HIT
    return BarResolution.CLOSE_EXIT


def resolve_trade(bar: DailyBar, sig: Signal, path: str) -> TradeResult:
    """path: 'conservative' | 'optimistic'."""
    res = classify_bar(bar, sig)

    if res == BarResolution.TARGET_HIT:
        pnl = (sig.target_price - sig.entry_price) / sig.entry_price
        return TradeResult(sig.date, res, pnl)

    if res == BarResolution.STOP_HIT:
        pnl = (sig.stop_price - sig.entry_price) / sig.entry_price
        return TradeResult(sig.date, res, pnl)

    if res == BarResolution.CLOSE_EXIT:
        pnl = (bar.close - sig.entry_price) / sig.entry_price
        return TradeResult(sig.date, res, pnl)

    # AMBIGUOUS — 경로별로 다르게 처리
    if path == "conservative":
        pnl = (sig.stop_price - sig.entry_price) / sig.entry_price
    elif path == "optimistic":
        # "손절 미발동, 진입가=목표가, 종가 청산" — 목표가에 진입한 것으로 보고
        # 그 시점 이후 종가까지 들고 간 것으로 계산
        pnl = (bar.close - sig.target_price) / sig.target_price
    else:
        raise ValueError(f"알 수 없는 path: {path}")
    return TradeResult(sig.date, res, pnl)


@dataclass
class G0Verdict:
    verdict: str                    # "pass" | "reject" | "hold" | "insufficient_bar_power"
    ambiguous_ratio: float
    e_conservative: float
    e_optimistic: float
    n_trades: int
    n_trading_days: int


def run_g0(
    bars: dict[str, DailyBar],
    signals: Sequence[Signal],
    cost_base: float,
    min_trades: int = 1000,
    min_trading_days: int = 500,
    ambiguous_ratio_threshold: float = 0.40,
) -> G0Verdict:
    """두 경로를 모두 계산하고 §5.4의 4분기 판정을 내린다.

    bars: {date: DailyBar} — signals[i].date로 조회.
    cost_base: phase0.config.costs.base_breakdown().base_total 등에서 주입.
    """
    cons_trades = [resolve_trade(bars[s.date], s, "conservative") for s in signals]
    opt_trades = [resolve_trade(bars[s.date], s, "optimistic") for s in signals]

    n = len(signals)
    ambiguous_ratio = (
        sum(1 for s in signals if classify_bar(bars[s.date], s) == BarResolution.AMBIGUOUS) / n
        if n else 0.0
    )

    def _e(trades: Sequence[TradeResult]) -> float:
        if not trades:
            return float("nan")
        pnls = [t.pnl_pct for t in trades]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x <= 0]
        p = len(wins) / len(pnls)
        W = sum(wins) / len(wins) if wins else 0.0
        L = -sum(losses) / len(losses) if losses else 0.0
        return e_trade(p, W, L, cost_base)

    e_cons = _e(cons_trades)
    e_opt = _e(opt_trades)
    trading_days = len({s.date for s in signals})

    if ambiguous_ratio > ambiguous_ratio_threshold:
        verdict = "insufficient_bar_power"
    elif n < min_trades or trading_days < min_trading_days:
        verdict = "insufficient_sample"
    elif e_opt <= 0:
        verdict = "reject"
    elif e_cons > 0:
        verdict = "pass"
    else:
        # e_opt > 0 and e_cons <= 0 → 부호 갈림
        verdict = "hold"

    return G0Verdict(
        verdict=verdict,
        ambiguous_ratio=ambiguous_ratio,
        e_conservative=e_cons,
        e_optimistic=e_opt,
        n_trades=n,
        n_trading_days=trading_days,
    )
