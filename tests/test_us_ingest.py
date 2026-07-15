import pandas as pd
import pytest

from phase0.data.us_ingest import clean_ohlcv, fetch_ohlcv


def _make_raw(rows):
    """rows: (date, open, high, low, close, volume) — yfinance(xs 이후) 형식 흉내."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame({
        "Open": [r[1] for r in rows],
        "High": [r[2] for r in rows],
        "Low": [r[3] for r in rows],
        "Close": [r[4] for r in rows],
        "Volume": [r[5] for r in rows],
    }, index=idx)


def test_clean_ohlcv_drops_zero_volume_holiday_rows():
    raw = _make_raw([
        ("2026-07-01", 100, 110, 95, 105, 1000),
        ("2026-07-02", 0, 0, 0, 0, 0),
    ])
    bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_high_below_low_with_warning():
    raw = _make_raw([
        ("2026-07-01", 100, 110, 95, 105, 1000),
        ("2026-07-02", 100, 90, 95, 92, 1000),   # high(90) < low(95)
    ])
    with pytest.warns(UserWarning, match="high"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_close_outside_range_with_warning():
    raw = _make_raw([
        ("2026-07-01", 100, 110, 95, 105, 1000),
        ("2026-07-02", 100, 110, 95, 120, 1000),   # close(120) > high(110)
    ])
    with pytest.warns(UserWarning, match="close"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_open_outside_range_with_warning():
    raw = _make_raw([
        ("2026-07-01", 100, 110, 95, 105, 1000),
        ("2026-07-02", 80, 110, 95, 105, 1000),    # open(80) < low(95)
    ])
    with pytest.warns(UserWarning, match="open"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_fetch_ohlcv_uses_injected_fetcher_not_real_network():
    raw = _make_raw([("2026-07-01", 100, 110, 95, 105, 1000)])
    bars = fetch_ohlcv("AAPL", "20260701", "20260701", fetcher=lambda t, s, e: raw)
    assert len(bars) == 1
    assert bars[0].volume == 1000


def test_fetch_ohlcv_converts_yyyymmdd_to_yfinance_date_format():
    seen = {}

    def spy_fetcher(ticker, start, end):
        seen["start"], seen["end"] = start, end
        return _make_raw([("2026-07-01", 100, 110, 95, 105, 1000)])

    fetch_ohlcv("AAPL", "20260701", "20260715", fetcher=spy_fetcher)
    assert seen["start"] == "20260701"   # fetcher는 원본 YYYYMMDD를 그대로 받음(변환은 기본 fetcher 내부에서만)
    assert seen["end"] == "20260715"
