"""VCB-Gap 전략: 거래량 확인 돌파 + 시가 갭 필터 (fable5 설계, 2026-07-14).

모멘텀 지속형. 전일이 20일 신고가를 거래량 동반으로 돌파하며 강하게
마감했고, 오늘 시가가 그 모멘텀을 부정(갭하락)하거나 이미 소진(과도한
갭상승)하지 않았다면 시가에 진입한다. 목표가/손절가는 ATR% 기반.

핵심 제약(README 참고): KIS 분봉 API는 당일 데이터만 제공하므로(이력 없음),
이 전략은 D-1 이전 일봉 + 오늘 시가만으로 신호를 결정한다 — 장중 데이터는
쓰지 않는다. G0 백테스터(phase0.backtest.g0_backtester)의 Signal/DailyBar
계약에 그대로 맞물리도록 설계됐다.

비용 기준선은 phase0.config.costs.base_breakdown().base_total에서 주입받아야
하며 여기서 하드코딩하지 않는다 — 이 모듈은 신호(Signal)만 만들고 비용
판정은 g0_backtester.run_g0가 담당한다.
"""

from __future__ import annotations

from phase0.backtest.g0_backtester import Signal
from phase0.data.pykrx_ingest import OhlcvBar

MIN_HISTORY = 22

# 데이터마이닝 방지용 사전 등록 격자(설계 시 확정, §목표/손절 배수는 이 안에서만
# 고른다). run_g0_backtest.py --grid로 6개 조합 전체를 한 번에, 투명하게 돈다.
K_TARGET_GRID = (1.2, 1.5, 2.0)
K_STOP_GRID = (0.75, 1.0)
PREREGISTERED_GRID = [(kt, ks) for kt in K_TARGET_GRID for ks in K_STOP_GRID]

_TICK_TABLE = [
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
    (float("inf"), 1_000),
]


def tick_size(price: float) -> int:
    """KRX 호가 단위 테이블. price가 속한 구간의 틱 사이즈를 반환."""
    for upper, size in _TICK_TABLE:
        if price < upper:
            return size
    return _TICK_TABLE[-1][1]


def round_up_to_tick(price: float) -> float:
    """price가 속한 구간의 호가 단위로 올림. 목표가/손절가 모두 올림 —
    목표가는 더 어렵게, 손절가는 더 일찍 걸리게 만들어 백테스트를 보수적으로 만든다."""
    size = tick_size(price)
    import math
    return math.ceil(price / size) * size


def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def vcb_gap_signal(
    bars: list[OhlcvBar],
    today_open: float,
    today_date: str,
    k_target: float = 1.5,
    k_stop: float = 1.0,
) -> Signal | None:
    """bars: D-1까지의 클렌징된 일봉(시간순, 최소 22개). today_open: D일 시가.

    조건 C1~C6을 전부 만족하면 오늘 시가에 진입하는 Signal을 반환, 아니면 None.
    k_target/k_stop: 목표가/손절가의 ATR% 배수 — PREREGISTERED_GRID 안에서만
    골라야 한다(자유 반복 금지, 데이터마이닝 방지).
    """
    if len(bars) < MIN_HISTORY:
        return None

    y, prev = bars[-1], bars[-2]              # D-1, D-2
    win = bars[-21:-1]                         # D-21 .. D-2 (20봉)

    clv = 1.0 if y.high == y.low else (y.close - y.low) / (y.high - y.low)
    hh20 = max(b.high for b in win)
    vol_avg20 = sum(b.volume for b in win) / len(win)

    trs = [
        _true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])   # TR[D-14..D-1]
    ]
    atr14 = sum(trs) / len(trs)
    atr_pct = atr14 / y.close

    gap = today_open / y.close - 1

    if not (y.close > y.open and clv >= 0.70):
        return None   # C1: 전일 강한 마감
    if not (y.close > hh20):
        return None   # C2: 전일 20일 신고가 돌파
    if not (y.volume >= 1.5 * vol_avg20):
        return None   # C3: 거래량 동반
    if not (-0.005 <= gap <= 0.020):
        return None   # C4: 시가 갭 필터
    if not (0.010 <= atr_pct <= 0.050):
        return None   # C5: 변동성 밴드
    if not (y.close / prev.close - 1 < 0.10):
        return None   # C6: 전일 상한가 근접 제외

    return Signal(
        date=today_date,
        entry_price=today_open,
        target_price=round_up_to_tick(today_open * (1 + k_target * atr_pct)),
        stop_price=round_up_to_tick(today_open * (1 - k_stop * atr_pct)),
    )
