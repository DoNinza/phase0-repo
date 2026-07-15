import datetime as dt

import pytest

from phase0.data.pykrx_ingest import OhlcvBar
from phase0.ml.gdr_filter import FEATURE_NAMES, extract_features, to_vector


def _flat(date, close=10000.0, volume=1000):
    return OhlcvBar(date=date, open=close, high=close + 100, low=close - 100, close=close, volume=volume)


def _bars():
    """21개 평범한 배경봉(flat) + D-1(y): 종가/거래량 모두 배경 대비 정확히 +1%/1.5배로 설계."""
    bars = [_flat(f"D{i:02d}") for i in range(21)]
    y = OhlcvBar(date="D21", open=10050.0, high=10200.0, low=9950.0, close=10100.0, volume=1500)
    bars.append(y)
    return bars


TODAY_OPEN = 10201.0   # gap_pct = 10201/10100 - 1 = 0.01 정확히
TODAY_DATE = "20260720"


def test_raises_when_insufficient_history():
    with pytest.raises(ValueError):
        extract_features(_bars()[:10], TODAY_OPEN, TODAY_DATE)


def test_features_match_hand_computed_values():
    f = extract_features(_bars(), TODAY_OPEN, TODAY_DATE)

    assert f["gap_pct"] == pytest.approx(0.01)
    assert f["clv"] == pytest.approx(0.6)              # (10100-9950)/(10200-9950)
    assert f["sma20_dist"] == pytest.approx(0.01)       # 10100/10000 - 1
    assert f["prev_day_return"] == pytest.approx(0.01)  # 10100/10000 - 1
    assert f["vol_ratio"] == pytest.approx(1.5)          # 1500/1000
    assert f["ret_5d"] == pytest.approx(0.01)
    assert f["ret_10d"] == pytest.approx(0.01)
    assert f["ret_20d"] == pytest.approx(0.01)
    # ATR14: 13일 flat->flat(TR=200) + 1일 flat->y(TR=250), 종가로 나눔
    expected_atr_pct = (13 * 200 + 250) / 14 / 10100.0
    assert f["atr_pct"] == pytest.approx(expected_atr_pct)
    # RSI14: 윈도우 내 유일한 변화가 +100(이득)뿐이라 손실=0 -> 100.0
    assert f["rsi14"] == pytest.approx(100.0)

    expected_date = dt.datetime.strptime(TODAY_DATE, "%Y%m%d")
    assert f["day_of_week"] == pytest.approx(float(expected_date.weekday()))
    assert f["month"] == pytest.approx(float(expected_date.month))


def test_to_vector_matches_feature_names_order():
    f = extract_features(_bars(), TODAY_OPEN, TODAY_DATE)
    vec = to_vector(f)
    assert len(vec) == len(FEATURE_NAMES)
    assert vec == [f[name] for name in FEATURE_NAMES]
