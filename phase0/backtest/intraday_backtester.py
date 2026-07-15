"""장중(intraday) 신호 백테스터 — 분봉 순서 기반 단일 경로 판정 (2026-07-15).

g0_backtester(일봉)와 근본적으로 다른 점: 일봉은 "그날 고가가 목표가를,
저가가 손절가를 둘 다 찍었으면 어느 게 먼저인지 모른다"는 구조적 한계
때문에 낙관/보수 이중 경로로 판정해야 했다(§5.4). 분봉이 있으면 같은
날 안에서도 시간 순서대로 어느 봉에서 무엇이 먼저 일어났는지 실제로
알 수 있다 — 그래서 이중 경로가 필요 없다. 같은 5분봉 안에서 고가·저가가
동시에 목표·손절을 둘 다 건드리는 극히 드문 경우만 보수적으로 손절
처리한다(사전 확정 규칙, IVR 설계서 §3 참고) — 이것도 하나의 결정론적
경로이지 이중 경로가 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from phase0.data.minute_bar_store import MinuteBar


@dataclass
class IntradaySignal:
    ticker: str
    date: str
    entry_time: str        # HHMMSS, 진입봉의 시각(봉 종료 라벨과 동일 규약)
    entry_price: float
    target_price: float
    stop_price: float


class IntradayResolution(Enum):
    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    TIME_EXIT = "time_exit"   # 강제청산 시각까지 목표·손절 모두 미도달


@dataclass
class IntradayTradeResult:
    ticker: str
    date: str
    resolution: IntradayResolution
    pnl_pct: float

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0


def resolve_intraday_trade(
    day_bars: Sequence[MinuteBar],
    signal: IntradaySignal,
    forced_exit_time: str,
) -> IntradayTradeResult:
    """day_bars: 그날 전체 분봉(시간순, MinuteBar.time = 봉 종료 라벨).

    진입봉(entry_time)부터 forced_exit_time까지 시간순으로 봉별 고가/저가를
    확인해 목표/손절 중 먼저 도달한 쪽으로 판정한다. 같은 봉 안에서 둘 다
    도달하면 손절로 판정(보수, 사전 확정). 끝까지 미도달이면 forced_exit_time
    봉의 종가로 청산한다.
    """
    path = [b for b in day_bars if signal.entry_time <= b.time <= forced_exit_time]
    if not path:
        raise ValueError(f"{signal.date} {signal.ticker}: entry_time~forced_exit_time 구간에 봉이 없음")

    for bar in path:
        hit_target = bar.high >= signal.target_price
        hit_stop = bar.low <= signal.stop_price
        if hit_stop:   # 동시 도달 포함 — 손절 우선(보수)
            pnl = (signal.stop_price - signal.entry_price) / signal.entry_price
            return IntradayTradeResult(signal.ticker, signal.date, IntradayResolution.STOP_HIT, pnl)
        if hit_target:
            pnl = (signal.target_price - signal.entry_price) / signal.entry_price
            return IntradayTradeResult(signal.ticker, signal.date, IntradayResolution.TARGET_HIT, pnl)

    exit_bar = path[-1]
    pnl = (exit_bar.close - signal.entry_price) / signal.entry_price
    return IntradayTradeResult(signal.ticker, signal.date, IntradayResolution.TIME_EXIT, pnl)
