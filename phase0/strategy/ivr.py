"""IVR (Intraday VWAP Reversion) — 장중 VWAP 평균회귀 전략 (fable 설계, 2026-07-15).

배경: 일봉 기반 4개 가설(VCB-Gap/GDR/GDR-V/VBP)이 KOSPI·미국 두 시장에서
전부 비용 대비 음수로 수렴한 뒤, 기획안이 명시한 다음 순서("장중
평균회귀, 분봉 축적분 활용")를 따른다. 처음으로 일봉이 아니라 5분봉
(키움 REST API 백필, README 참고)을 쓰는 가설이다.

핵심 가설: KOSPI 대형주가 장중 당일 VWAP 아래로 비정상적으로(그러나
뉴스급은 아니게) 이탈한 뒤 하락이 멈추는 첫 신호(양봉)가 나오면, 이는
정보가 아니라 일시적 유동성 충격이 만든 왜곡일 확률이 높고 같은 세션
안에 VWAP 방향으로 되돌아온다. 일봉 GDR과 달리 "오늘 시가" 단일
데이터포인트가 아니라 장중 여러 시점의 실제 체결 누적(VWAP)을 앵커로
쓰고, "하락이 멈춘 뒤"(C4)에만 진입한다는 게 구조적 차이다.

데이터마이닝 방지: 이 분봉 데이터셋에 대한 사전등록 1회분이다. 8개
격자 조합의 결과가 어떻게 나오든 조건·파라미터·판정 규칙을 결과를 본
뒤에 수정하지 않는다.
"""

from __future__ import annotations

from typing import Sequence

from phase0.backtest.intraday_backtester import IntradaySignal
from phase0.data.minute_bar_store import MinuteBar
from phase0.strategy.vcb_gap import round_up_to_tick

# 사전등록 격자(설계 시 확정, 2026-07-15) — d(이탈 트리거) x f(목표 회귀율) x k_stop(손절 배수)
DEV_TRIGGER_GRID = (0.010, 0.015)
TARGET_FRAC_GRID = (0.6, 1.0)
STOP_MULT_GRID = (0.75, 1.25)
PREREGISTERED_GRID = [
    (d, f, k) for d in DEV_TRIGGER_GRID for f in TARGET_FRAC_GRID for k in STOP_MULT_GRID
]

# 고정 상수(전부 설계 시 확정 — 결과 보고 조정 금지)
EVAL_WINDOW = ("093500", "130000")   # C1: 신호봉 평가창(봉 종료 라벨 기준)
DEV_CAP = 0.030                      # C3: 과대이탈 상한(정보 이벤트 배제)
CRASH_FLOOR_MULT = 0.93              # C3: 전일종가 대비 급락 배제 기준
GAP_CAP = 0.030                      # C5: 시가 갭 상한(뉴스데이 배제)
RECHECK_MULT = 0.7                   # C6: 진입 시점 재확인 계수
FORCED_EXIT_TIME = "151500"          # 강제청산 시각(봉 종료 라벨)


def _vwap_step(cum_pv: float, cum_vol: float, bar: MinuteBar) -> tuple[float, float, float]:
    typical = (bar.high + bar.low + bar.close) / 3
    cum_pv += typical * bar.volume
    cum_vol += bar.volume
    vwap = cum_pv / cum_vol if cum_vol > 0 else 0.0
    return cum_pv, cum_vol, vwap


def ivr_signal_for_day(
    ticker: str,
    day_bars: Sequence[MinuteBar],
    prev_close: float,
    d: float,
    f: float,
    k_stop: float,
) -> IntradaySignal | None:
    """day_bars: 그날 하루 전체 분봉(시간순, 봉 1부터). prev_close: 전일 마지막 봉 종가.

    C1~C6을 전부 만족하는 그날의 첫 신호봉을 찾아 다음 봉 시가에 진입하는
    IntradaySignal을 반환. 하루 최대 1건 — d/f/k_stop은 PREREGISTERED_GRID
    안에서만 고른다.
    """
    if not day_bars or prev_close <= 0:
        return None

    day_open = day_bars[0].open
    if abs(day_open / prev_close - 1) > GAP_CAP:
        return None   # C5: 갭 이벤트일 — 당일 전체 신호 금지

    cum_pv, cum_vol = 0.0, 0.0
    for i, bar in enumerate(day_bars):
        cum_pv, cum_vol, vwap = _vwap_step(cum_pv, cum_vol, bar)
        if vwap <= 0:
            continue
        dev = (vwap - bar.close) / vwap

        # C3: 과대이탈 또는 급락 -- 당일 전체 신호 금지(평가창 밖에서도 계속 감시)
        if dev > DEV_CAP or bar.close < prev_close * CRASH_FLOOR_MULT:
            return None

        if not (EVAL_WINDOW[0] <= bar.time <= EVAL_WINDOW[1]):
            continue   # C1: 평가창 밖 -- 신호봉 후보 아님(VWAP 누적은 계속)
        if dev < d:
            continue   # C2: 이탈 트리거 미달
        if not (bar.close > bar.open):
            continue   # C4: 안정화 확인봉(양봉) 아님

        if i + 1 >= len(day_bars):
            return None   # 다음 봉(진입봉)이 없음
        entry_bar = day_bars[i + 1]
        entry_price = entry_bar.open
        if entry_price <= 0:
            return None

        dev_entry = (vwap - entry_price) / entry_price   # C6: 신호봉 종가 시점 VWAP 동결
        if dev_entry < RECHECK_MULT * d:
            return None   # C6 재확인 실패 -- 당일 신호 소진(재평가 안 함)

        target = round_up_to_tick(entry_price * (1 + f * dev_entry))
        stop = round_up_to_tick(entry_price * (1 - k_stop * dev_entry))

        return IntradaySignal(
            ticker=ticker, date=day_bars[0].date, entry_time=entry_bar.time,
            entry_price=entry_price, target_price=target, stop_price=stop,
        )

    return None
