"""GDR 전략: 갭하락 과잉반응 반등 (Gap-Down Rebound) (fable5 설계, 2026-07-15).

단기 평균회귀형 — VCB-Gap(모멘텀 지속형)의 구조적 대체 가설.

배경: VCB-Gap은 사전 등록 격자 6개 조합 전부에서 E_trade가 -0.58%~-0.64%로,
무엇보다 '엣지 없음' 중립 기준선(≈-0.12%)보다도 유의하게 나빴다. 즉 강세
마감+돌파 뒤 시가 매수는 대형주에서 단기 '역방향' 드리프트(약 -0.5%/거래)를
골라 담았다는 뜻이다. 이 관측 자체가 이 유니버스에 단기 반전(reversal)
성향이 살아 있다는 방증이므로, GDR은 정확히 그 반대 부호를 조건화한다:
과매도 쪽 이탈(비정상 갭하락)을 사서 당일 되돌림을 수확한다.

당일 청산 제약과의 구조적 정합성(VCB-Gap 실패의 교훈): 돌파 지속은 여러 날에
걸쳐 실현되는 현상이라 당일 강제 청산과 어긋났다. 반면 갭하락 과잉반응은
'왜곡이 시초가 단일가에서 만들어지고', 그 교정(갭 메우기)도 본질적으로 같은
세션 안에서 일어나는 현상이다 — 전일 종가가 당일 장중의 자연스러운 자석/
저항으로 작동하므로, 엣지가 실재한다면 당일 안에 실현되는 것이 기본형이다.

핵심 제약(README): KIS 분봉 API는 당일 데이터만 제공 — D-1 이전 일봉 +
오늘 시가만으로 신호를 결정한다. G0 백테스터의 Signal/DailyBar 계약에 그대로
맞물린다. 비용은 phase0.config.costs에서 주입 — 여기 하드코딩하지 않는다.
"""

from __future__ import annotations

from phase0.backtest.g0_backtester import Signal
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vcb_gap import round_up_to_tick

MIN_HISTORY = 22

# 데이터마이닝 방지용 사전 등록 격자(설계 시 확정, 2026-07-15).
# f_fill: 목표가 = 시가 + f_fill x (전일종가 - 시가) — 갭 되메움 비율.
# k_stop: 손절가 = 시가 x (1 - k_stop x ATR%). VCB-Gap(0.75/1.0)보다 의도적으로
# 넓다: 갭하락 시가는 반등 전에 아래로 한 번 더 흔들리는 일이 잦아, 타이트한
# 손절은 평균회귀 트레이드의 승리를 조직적으로 패배로 바꾼다.
F_FILL_GRID = (0.6, 0.8, 1.0)
K_STOP_GRID = (1.0, 1.5)
PREREGISTERED_GRID = [(f, k) for f in F_FILL_GRID for k in K_STOP_GRID]

# 진입 조건 상수(전부 설계 시 확정 — 결과 보고 조정 금지)
TREND_FLOOR = 0.98        # C1: 전일 종가 >= 0.98 x SMA20 (하락추세 낙하 배제)
GAP_FLOOR_ABS = 0.012     # C2: 갭 <= -1.2% (절대 최소 — 비용 대비 유의미한 왜곡)
GAP_FLOOR_ATR = 0.75      # C2: 갭 <= -0.75 x ATR% (적응 최소 — '그 종목 기준' 비정상)
GAP_CAP = 0.045           # C2: 갭 >= -4.5% (진짜 악재/투매·하한가 소용돌이 배제)
PREV_DAY_CRASH = -0.05    # C3: 전일 수익률 > -5% (이미 급락 중인 종목 배제)
ATR_BAND = (0.010, 0.050) # C4: 변동성 밴드 (VCB-Gap과 동일 밴드 승계)
EX_DIV_WINDOW = ("1222", "1231")  # C5: 12월 배당락 시즌(MMDD) 제외 —
# 12월 결산 배당락 갭하락은 기계적 가격 조정이지 과잉반응이 아니며(되메움
# 기대 자체가 없음), pykrx 일봉은 현금배당 미조정이라 이 구간 신호는 오염원.


def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def gap_rebound_signal(
    bars: list[OhlcvBar],
    today_open: float,
    today_date: str,
    f_fill: float = 0.8,
    k_stop: float = 1.0,
) -> Signal | None:
    """bars: D-1까지의 클렌징된 일봉(시간순, 최소 22개). today_open: D일 시가.

    조건 C1~C5를 전부 만족하면 오늘 시가에 진입하는 Signal을 반환, 아니면 None.
    f_fill/k_stop은 PREREGISTERED_GRID 안에서만 고른다(자유 반복 금지).
    """
    if len(bars) < MIN_HISTORY:
        return None

    # C5: 배당락 시즌 제외 (today_date: YYYYMMDD)
    if EX_DIV_WINDOW[0] <= today_date[4:8] <= EX_DIV_WINDOW[1]:
        return None

    y, prev = bars[-1], bars[-2]              # D-1, D-2

    sma20 = sum(b.close for b in bars[-20:]) / 20

    trs = [
        _true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])   # TR[D-14..D-1]
    ]
    atr14 = sum(trs) / len(trs)
    atr_pct = atr14 / y.close

    gap = today_open / y.close - 1

    if not (y.close >= TREND_FLOOR * sma20):
        return None   # C1: 하락추세 아님 (건강한 종목의 왜곡만 산다)
    gap_floor = max(GAP_FLOOR_ABS, GAP_FLOOR_ATR * atr_pct)
    if not (-GAP_CAP <= gap <= -gap_floor):
        return None   # C2: 비정상 갭하락 밴드 (너무 얕지도, 악재급도 아님)
    if not (y.close / prev.close - 1 > PREV_DAY_CRASH):
        return None   # C3: 전일 급락 배제 (연쇄 투매의 둘째 날을 사지 않음)
    if not (ATR_BAND[0] <= atr_pct <= ATR_BAND[1]):
        return None   # C4: 변동성 밴드

    # 목표가: 갭 부분 되메움. 전일 종가가 상한 앵커(자석/저항) — f_fill<=1.0.
    target = today_open + f_fill * (y.close - today_open)
    # 손절가: ATR% 기반 재난 방지선(갭 크기가 아니라 종목 변동성 기준).
    stop = today_open * (1 - k_stop * atr_pct)

    # 올림 반올림은 vcb_gap과 동일한 보수화: 목표가는 더 어렵게, 손절은 더 일찍.
    return Signal(
        date=today_date,
        entry_price=today_open,
        target_price=round_up_to_tick(target),
        stop_price=round_up_to_tick(stop),
    )
