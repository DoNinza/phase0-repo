"""이벤트(PEAD) 다일 보유 백테스터 — 시간청산·갭 보수 체결 단일 경로
(docs/news_fundamentals_전략_기획안.md §6, PEAD Phase 3).

g0_backtester(일봉 당일청산)를 그대로 재사용하지 않는 이유는 기획안 §6에
문서화돼 있다(해소 단위가 다일 창이라는 점, target_price가 없다는 점,
낙관/보수 이중 경로의 존재 이유 자체가 소멸한다는 점). intraday_backtester
(분봉, 시간순 단일 경로 판정)와 같은 설계 철학을 일봉 다일 시퀀스에
적용한 것이라고 보면 된다 — 다만 "동시 도달" 대신 "갭으로 손절가 밑에서
시가가 열림"이 유일한 잔여 불확실성이라, 그 경우엔 `fill = min(그날
시가, 손절가)`(불리한 쪽 체결) 단일 보수 규칙으로 처리한다(§6).

목표가가 없다 — 드리프트 가설의 반증점은 보유기간 누적수익이지 특정
가격 도달이 아니기 때문(기획안 §3). 그래서 이 하네스엔 "target_hit"
분기 자체가 없다: 손절 아니면 시간청산 둘 중 하나뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from phase0.backtest.g0_backtester import DailyBar
from phase0.engine.core import e_trade


@dataclass
class EventSignal:
    """PEAD 신호. entry_date는 D+1(공시 접수일 다음 거래일) 시가 진입 —
    look-ahead 방지 설계는 phase0.data.dart_ingest/phase0.strategy.pead
    쪽 책임이고, 여기선 이미 확정된 신호만 받는다."""

    ticker: str
    entry_date: str
    entry_price: float
    stop_price: float
    hold_days: int  # H — 사전등록 격자의 보유기간(거래일)


class EventResolution(Enum):
    STOP_HIT = "stop_hit"
    TIME_EXIT = "time_exit"


@dataclass
class EventTradeResult:
    ticker: str
    entry_date: str
    exit_date: str
    resolution: EventResolution
    pnl_pct: float  # 비용 미차감
    days_held: int

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0


def resolve_event_trade(
    bars: Sequence[DailyBar],
    signal: EventSignal,
) -> EventTradeResult:
    """bars: entry_date부터 시간순으로 최소 signal.hold_days+1개 이상의 일봉
    (entry_date 당일 봉 포함, entry_date == bars[0].date여야 한다).

    진입일 당일부터 hold_days거래일째까지 시간순으로 손절 도달을 확인한다.
    - 진입일 당일: entry_price(=그날 시가)로 이미 진입했으므로, 그날 저가가
      손절가 이하면 손절가 그대로 체결(갭이 아니라 당일 중 하락 — entry가
      시가이므로 갭-스루가 발생할 수 없는 유일한 날).
    - 이후 날짜들: 시가가 손절가 이하로 갭 하락했으면 `fill = min(시가,
      손절가)`(불리한 쪽), 갭 없이 저가만 손절가를 찍었으면 손절가 그대로.
    - hold_days거래일째까지 손절 미도달이면 그날 종가로 시간청산.
    """
    if len(bars) < signal.hold_days + 1:
        raise ValueError(
            f"{signal.ticker} {signal.entry_date}: 보유기간({signal.hold_days}거래일)에 "
            f"필요한 일봉({signal.hold_days + 1}개)보다 적게 주어짐({len(bars)}개)"
        )
    if bars[0].date != signal.entry_date:
        raise ValueError(f"bars[0].date({bars[0].date})가 entry_date({signal.entry_date})와 다름")

    entry_bar = bars[0]
    if entry_bar.low <= signal.stop_price:
        pnl = (signal.stop_price - signal.entry_price) / signal.entry_price
        return EventTradeResult(
            signal.ticker, signal.entry_date, entry_bar.date,
            EventResolution.STOP_HIT, pnl, days_held=0,
        )

    for day_idx in range(1, signal.hold_days + 1):
        bar = bars[day_idx]
        if bar.open <= signal.stop_price:
            fill = bar.open  # 갭 하락 — 시가가 이미 손절가 이하, 그 시가로 체결(불리한 쪽)
        elif bar.low <= signal.stop_price:
            fill = signal.stop_price  # 갭 없이 장중 도달
        else:
            continue
        pnl = (fill - signal.entry_price) / signal.entry_price
        return EventTradeResult(
            signal.ticker, signal.entry_date, bar.date,
            EventResolution.STOP_HIT, pnl, days_held=day_idx,
        )

    exit_bar = bars[signal.hold_days]
    pnl = (exit_bar.close - signal.entry_price) / signal.entry_price
    return EventTradeResult(
        signal.ticker, signal.entry_date, exit_bar.date,
        EventResolution.TIME_EXIT, pnl, days_held=signal.hold_days,
    )


@dataclass
class EventBacktestVerdict:
    e_net: float
    n_trades: int
    n_trading_days: int  # 서로 다른 entry_date 수


def _expectancy(trades: Sequence[EventTradeResult], cost_base: float) -> float:
    if not trades:
        return float("nan")
    pnls = [t.pnl_pct for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    p = len(wins) / len(pnls)
    W = sum(wins) / len(wins) if wins else 0.0
    L = -sum(losses) / len(losses) if losses else 0.0
    return e_trade(p, W, L, cost_base)


def run_event_backtest(
    trades: Sequence[EventTradeResult],
    cost_base: float,
) -> EventBacktestVerdict:
    """이미 resolve_event_trade로 해소된 거래 목록에서 E_net을 계산한다.

    g0_backtester.run_g0와 달리 여기선 판정(pass/reject)을 내리지 않는다
    — 8칸 전수 보고가 사전등록 규약(기획안 §5·§7)이라, 판정은 리포트
    스크립트(scripts/run_pead_backtest.py) 층에서 8칸을 한꺼번에 놓고
    사람이 본다.
    """
    e_net = _expectancy(trades, cost_base)
    trading_days = len({t.entry_date for t in trades})
    return EventBacktestVerdict(e_net=e_net, n_trades=len(trades), n_trading_days=trading_days)
