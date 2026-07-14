"""VBP 전략: 거래량 앵커 눌림목 반등 (fable 설계, 2026-07-15).

세 번째 가설 — VCB-Gap(모멘텀 지속형, 실패)과 GDR(평균회귀형, 부분 지지)
둘 다와 구조적으로 다르다. 핵심 가설: 대량 거래를 동반한 결정적 돌파로
만들어진 가격대(앵커 레벨)를 1~3일간 저거래량으로 방어한 종목이 약세
시가로 출발하면, 그 시가는 "실수요가 확인된 지지대 위에서의 단기 과매도"
이므로 직전 스윙 고점(H_ref)이라는 이미 며칠 안에 실제로 찍힌 가까운
목표를 향해 세션 내에 되돌아온다.

VCB-Gap 실패 진단에 대한 명시적 대응:
- 한계 돌파(노이즈)가 아니라 ATR 대비 결정적 돌파만 앵커로 인정(C1).
- 돌파 후 종가가 레벨을 하회한 적 없어야 함 — 휩쏘의 시그니처를 사전에
  걸러낸다(C4).
- 돌파 직후 대량거래 눌림(분산)이 아니라 거래량 수축 속 눌림만 인정(C5).
- 강세 시가가 아니라 약세~보합 시가를 산다 — 두 실험이 공통으로 보여준
  단기 반전 드리프트와 같은 방향(C6).
- 손절이 진입가가 아니라 돌파 레벨(구조) 기준 — 손절되는 거래는 "레벨이
  무너졌다"는 가설의 반증점과 정확히 일치한다.

데이터 제약: D-1까지의 일봉 + 오늘 시가만 사용. 분봉/장중 시각 정보는
전혀 없다(KIS 분봉 API는 당일 데이터만 제공, 과거 이력 없음) — 그래서
"시간대 필터"는 문자 그대로 구현하지 않고, 앵커일의 거래량 스파이크 +
눌림 구간의 거래량 수축이라는 다일(多日) 거래량 궤적으로 대체한다.
"""

from __future__ import annotations

from phase0.backtest.g0_backtester import Signal
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vcb_gap import round_up_to_tick

MIN_HISTORY = 24   # 20봉 앵커 윈도우 + 최대 앵커 오프셋(D-4)

# 데이터마이닝 방지용 사전 등록 격자(설계 시 확정, 2026-07-15).
F_RET_GRID = (0.5, 0.75, 1.0)
K_STOP_GRID = (0.75, 1.25)
PREREGISTERED_GRID = [(f, k) for f in F_RET_GRID for k in K_STOP_GRID]

# 고정 상수(전부 설계 시 확정 — 결과 보고 조정 금지)
BREAKOUT_ATR_MULT = 0.30       # C1: 앵커일 돌파 강도(ATR 대비 결정적 돌파)
VOLUME_SPIKE_MULT = 2.0        # C2: 앵커일 거래량 스파이크 배율
ANCHOR_DAY_CRASH_CAP = 0.10    # C3: 앵커일 상한가 근접 제외
PULLBACK_VOL_CAP = 0.7         # C5: 눌림 구간 거래량 상한(앵커일 대비)
GAP_BAND = (-0.035, 0.000)     # C6: 약세~보합 시가만
LEVEL_TOLERANCE_ATR = 0.25     # C6: 시가 시점 레벨 생존 허용치
MIN_TARGET_DIST_ATR = 1.0      # C7: 목표까지 최소 거리(경제성)
ATR_BAND = (0.010, 0.050)      # C8: 변동성 밴드(VCB-Gap/GDR과 동일 승계)
EX_DIV_WINDOW = ("1222", "1231")  # C9: 12월 배당락 시즌 제외
ANCHOR_OFFSETS = (2, 3, 4)     # A ∈ {D-2, D-3, D-4} — 가장 최근 우선 탐색
ANCHOR_WINDOW = 20             # 앵커일 직전 N봉으로 HH20_A/V20_A 계산


def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _atr14_at(bars: list[OhlcvBar], end_idx: int) -> float:
    """bars[end_idx]를 'D-1'로 보고 TR[end_idx-13..end_idx]의 14봉 ATR."""
    prevs = bars[end_idx - 14:end_idx]
    currs = bars[end_idx - 13:end_idx + 1]
    trs = [_true_range(p.close, b.high, b.low) for p, b in zip(prevs, currs)]
    return sum(trs) / len(trs) if trs else 0.0


def _find_anchor(bars: list[OhlcvBar]) -> tuple[int, float] | None:
    """A ∈ {D-2,D-3,D-4} 중 가장 최근으로 C1~C3을 만족하는 날을 앵커로 확정.

    가장 최근 후보가 이후 C4에서 탈락해도 더 오래된 후보로 넘어가지 않는다
    (구현 모호성 제거 — 호출부에서 C4 실패 시 그대로 None 반환하는 흐름).
    """
    n = len(bars)
    for offset in ANCHOR_OFFSETS:
        a_idx = n - offset
        if a_idx - ANCHOR_WINDOW < 0 or a_idx < 1:
            continue
        a = bars[a_idx]
        win = bars[a_idx - ANCHOR_WINDOW:a_idx]
        hh20_a = max(b.high for b in win)
        v20_a = sum(b.volume for b in win) / len(win)
        atr_a = _atr14_at(bars, a_idx)
        if atr_a <= 0:
            continue
        if not (a.close - hh20_a >= BREAKOUT_ATR_MULT * atr_a):
            continue   # C1: 돌파 강도(ATR 정규화) 미달
        if not (a.volume >= VOLUME_SPIKE_MULT * v20_a):
            continue   # C2: 거래량 스파이크 미달
        prev_a = bars[a_idx - 1]
        if prev_a.close <= 0 or not (a.close / prev_a.close - 1 < ANCHOR_DAY_CRASH_CAP):
            continue   # C3: 앵커일 상한가 근접(블로우오프) 제외
        return a_idx, hh20_a
    return None


def vbp_signal(
    bars: list[OhlcvBar],
    today_open: float,
    today_date: str,
    f_ret: float = 0.75,
    k_stop: float = 1.25,
) -> Signal | None:
    """bars: D-1까지의 클렌징된 일봉(시간순, 최소 24개). today_open: D일 시가.

    C1~C9를 전부 만족하면 오늘 시가에 진입하는 Signal을 반환, 아니면 None.
    f_ret/k_stop은 PREREGISTERED_GRID 안에서만 고른다.
    """
    if len(bars) < MIN_HISTORY:
        return None

    if EX_DIV_WINDOW[0] <= today_date[4:8] <= EX_DIV_WINDOW[1]:
        return None   # C9

    anchor = _find_anchor(bars)
    if anchor is None:
        return None
    a_idx, hh20_a = anchor
    n = len(bars)
    a = bars[a_idx]

    for i in range(a_idx + 1, n):
        if bars[i].close < hh20_a:
            return None   # C4: 돌파 후 종가가 레벨을 하회한 적 있음(휩쏘 시그니처)

    y = bars[-1]
    if not (y.close < a.close):
        return None   # C5: 눌림이 실재해야 함(없으면 아직 연장 중)
    for i in range(a_idx + 1, n):
        if bars[i].volume > PULLBACK_VOL_CAP * a.volume:
            return None   # C5: 눌림 구간 거래량이 수축돼야 함(분산 배제)

    atr = _atr14_at(bars, n - 1)
    if atr <= 0:
        return None
    atr_pct = atr / y.close
    if not (ATR_BAND[0] <= atr_pct <= ATR_BAND[1]):
        return None   # C8: 변동성 밴드

    gap = today_open / y.close - 1
    if not (GAP_BAND[0] <= gap <= GAP_BAND[1]):
        return None   # C6: 약세~보합 시가만
    if not (today_open >= hh20_a - LEVEL_TOLERANCE_ATR * atr):
        return None   # C6: 시가 시점 레벨이 대체로 살아 있어야 함

    h_ref = max(b.high for b in bars[a_idx:n])   # A일부터 D-1까지 최고 고가
    if not (h_ref - today_open >= MIN_TARGET_DIST_ATR * atr):
        return None   # C7: 목표까지 최소 거리(경제성)

    target = today_open + f_ret * (h_ref - today_open)
    stop = hh20_a - k_stop * atr

    return Signal(
        date=today_date,
        entry_price=today_open,
        target_price=round_up_to_tick(target),
        stop_price=round_up_to_tick(stop),
    )
