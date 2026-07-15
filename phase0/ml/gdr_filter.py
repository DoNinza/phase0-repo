"""GDR 신호 스마트 필터용 특징 추출 (2026-07-15).

배경: 4개 규칙 기반 가설(VCB-Gap/GDR/GDR-V/VBP)이 전부 실데이터로 기각·
근거소멸됐다. 완전히 새로운 신호 생성 로직을 만드는 대신, 이미 만들어진
GDR의 조건(C1~C5)이 골라낸 신호 집합 위에서 "이 신호가 실제로 이길
확률"을 클래식 ML(로지스틱 회귀)로 추정해 승률 낮은 신호를 걸러내는
스마트 필터로 쓴다 — 표본 요구량이 크로스섹셔널 랭킹보다 훨씬 낮다.

데이터 제약 승계: D-1까지의 일봉 + 오늘 시가만 사용(룩어헤드 없음).
특징은 전부 이 정보로만 계산된다.

MIN_HISTORY=22는 gap_rebound.py와 동일 — 이 필터는 GDR이 이미 신호를
낸 날에만 적용되므로 별도로 더 긴 이력을 요구하지 않는다.
"""

from __future__ import annotations

import datetime as dt

from phase0.data.pykrx_ingest import OhlcvBar

MIN_HISTORY = 22

FEATURE_NAMES = [
    "gap_pct",
    "atr_pct",
    "clv",
    "sma20_dist",
    "prev_day_return",
    "vol_ratio",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "rsi14",
    "day_of_week",
    "month",
]


def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _atr14(bars: list[OhlcvBar]) -> float:
    trs = [
        _true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])   # TR[D-14..D-1] — gap_rebound.py와 동일 관례
    ]
    return sum(trs) / len(trs)


def _rsi14(bars: list[OhlcvBar]) -> float:
    closes = [b.close for b in bars[-15:]]   # 15개 종가 -> 14개 변화분
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def extract_features(bars: list[OhlcvBar], today_open: float, today_date: str) -> dict[str, float]:
    """bars: D-1까지의 클렌징된 일봉(시간순, 최소 22개). today_open/today_date: D일 시가·날짜.

    반환 dict의 키는 FEATURE_NAMES와 순서까지 일치한다. GDR의 C1~C5를 만족한
    신호에 대해서만 호출한다고 가정 — 그 자체는 검증하지 않는다(호출부 책임).
    """
    if len(bars) < MIN_HISTORY:
        raise ValueError(f"bars 길이({len(bars)})가 MIN_HISTORY({MIN_HISTORY})보다 작습니다")

    y, prev = bars[-1], bars[-2]
    win20 = bars[-21:-1]
    sma20 = sum(b.close for b in win20) / len(win20)
    vol_avg20 = sum(b.volume for b in win20) / len(win20)
    atr_pct = _atr14(bars) / y.close
    clv = 1.0 if y.high == y.low else (y.close - y.low) / (y.high - y.low)
    date_obj = dt.datetime.strptime(today_date, "%Y%m%d")

    return {
        "gap_pct": today_open / y.close - 1,
        "atr_pct": atr_pct,
        "clv": clv,
        "sma20_dist": y.close / sma20 - 1,
        "prev_day_return": y.close / prev.close - 1,
        "vol_ratio": y.volume / vol_avg20 if vol_avg20 > 0 else 0.0,
        "ret_5d": y.close / bars[-6].close - 1,
        "ret_10d": y.close / bars[-11].close - 1,
        "ret_20d": y.close / bars[-21].close - 1,
        "rsi14": _rsi14(bars),
        "day_of_week": float(date_obj.weekday()),
        "month": float(date_obj.month),
    }


def to_vector(features: dict[str, float]) -> list[float]:
    """FEATURE_NAMES 순서로 dict를 벡터화 — sklearn 입력용."""
    return [features[name] for name in FEATURE_NAMES]
