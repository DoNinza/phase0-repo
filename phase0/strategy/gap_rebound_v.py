"""GDR-V 전략: 갭하락 과잉반응 반등 + 거래량 확인 (fable 설계, 2026-07-15).

GDR(gap_rebound.py)의 C1~C5는 전혀 바꾸지 않고, C6(거래량 확인)을 AND로
추가한 별도 가설이다 — 기존 GDR의 이미 보고된 결과(6개 조합, 전부 마이너스
이지만 무편향 기준선보다 나음)를 덮어쓰지 않고, GDR-V는 새로 사전 등록해
독립적으로 검증한다.

핵심 근거(Campbell-Grossman-Wang류 거래량-반전 이론): 전일 거래량이 평소보다
컸다는 것은 갭하락에 앞서 매도 압력이 이미 실물로 시장을 통과했다는 뜻이고,
이런 유동성발 하락은 평균회귀 확률이 높다. 반대로 거래량 없는 갭하락은 새
정보에 대한 재평가(정보발)일 확률이 높아 되돌아오지 않는다. C6은 이 두
모집단을 갭 크기·ATR만으로는 못 가르는 것을 거래량이라는 독립 채널로
가르려는 시도다.

주의(룩어헤드 방지): 진입 시점(오늘 시가)에 오늘 거래량은 아직 존재하지
않는 정보이므로, C6은 반드시 D-1 거래량만 쓴다. D-1 자신을 20일 평균에서
제외하는 이유는 그날의 스파이크가 스스로의 기준선을 끌어올리는 자기잠식을
막기 위함이다.
"""

from __future__ import annotations

from phase0.backtest.g0_backtester import Signal
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.gap_rebound import MIN_HISTORY, gap_rebound_signal

# 데이터마이닝 방지용 사전 등록 격자(설계 시 확정, 2026-07-15). f_fill/k_stop은
# 기존 GDR과 완전히 동일한 6칸을 유지해 칸별로 GDR과 GDR-V를 1:1 대응
# 비교할 수 있게 한다. v_mult만 새로 추가된 파라미터(2값).
F_FILL_GRID = (0.6, 0.8, 1.0)
K_STOP_GRID = (1.0, 1.5)
V_MULT_GRID = (1.2, 1.5)
PREREGISTERED_GRID = [
    (f, k, v) for f in F_FILL_GRID for k in K_STOP_GRID for v in V_MULT_GRID
]

VOLUME_AVG_WINDOW = 20   # 고정 상수 — 격자에 넣지 않음
DAY_CHANGE_CAP = 0.30    # C6 위생 규칙: 자본이벤트 추정 컷오프


def _volume_confirmed(bars: list[OhlcvBar], v_mult: float) -> bool:
    """C6: V(D-1) >= v_mult * AvgV20(D-21..D-2). 위생 규칙(거래정지·자본이벤트) 포함."""
    y = bars[-1]
    win = bars[-(VOLUME_AVG_WINDOW + 1):-1]   # D-21..D-2 (D-1 제외 20봉)
    if len(win) < VOLUME_AVG_WINDOW:
        return False

    prevs = [bars[-(VOLUME_AVG_WINDOW + 2)]] + win[:-1]
    for p, b in zip(prevs, win):
        if b.volume == 0:
            return False   # 거래정지일 포함 시 스킵
        if p.close <= 0 or abs(b.close / p.close - 1) > DAY_CHANGE_CAP:
            return False   # 자본이벤트(액면분할·유상증자 등) 추정 시 스킵

    avg_v20 = sum(b.volume for b in win) / len(win)
    return y.volume >= v_mult * avg_v20


def gap_rebound_v_signal(
    bars: list[OhlcvBar],
    today_open: float,
    today_date: str,
    f_fill: float = 0.8,
    k_stop: float = 1.0,
    v_mult: float = 1.5,
) -> Signal | None:
    """bars: D-1까지의 클렌징된 일봉(시간순, 최소 22개 + 거래량 평균창 확보).

    C1~C5(gap_rebound_signal 그대로) AND C6(거래량 확인)을 전부 만족해야 신호.
    f_fill/k_stop/v_mult은 PREREGISTERED_GRID 안에서만 고른다.
    """
    if len(bars) < MIN_HISTORY:   # gap_rebound_signal과 _volume_confirmed 둘 다 22봉이면 충분
        return None
    if not _volume_confirmed(bars, v_mult):
        return None   # C6
    return gap_rebound_signal(bars, today_open, today_date, f_fill=f_fill, k_stop=k_stop)
