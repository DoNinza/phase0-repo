import pandas as pd
import pytest

from phase0.data.pykrx_ingest import (
    OhlcvBar, clean_ohlcv, fetch_ohlcv, fetch_universe, to_daily_bar,
    UniverseUnavailableError,
)


def _make_raw(rows):
    """rows: (date, open, high, low, close, volume) — pykrx get_market_ohlcv 형식 흉내."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame({
        "시가": [r[1] for r in rows],
        "고가": [r[2] for r in rows],
        "저가": [r[3] for r in rows],
        "종가": [r[4] for r in rows],
        "거래량": [r[5] for r in rows],
        "등락률": [0.0 for _ in rows],
    }, index=idx)


def test_clean_ohlcv_drops_zero_volume_holiday_rows():
    raw = _make_raw([
        ("20260701", 100, 110, 95, 105, 1000),
        ("20260702", 0, 0, 0, 0, 0),   # 휴장일이 날짜 인덱스에 섞여 들어온 경우
    ])
    bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_high_below_low_with_warning():
    # 실측(2026-07-15): 10년 배치에서 액면분할 조정 반올림으로 하루치가
    # 이런 위반을 냈다. 그 하루만 빼고 나머지 이력은 살려야 한다 — 예외로
    # 종목 전체를 버리면 삼성전자 같은 핵심 종목이 통째로 빠진다.
    raw = _make_raw([
        ("20260701", 100, 110, 95, 105, 1000),
        ("20260702", 100, 90, 95, 92, 1000),   # 고가(90) < 저가(95)
    ])
    with pytest.warns(UserWarning, match="고가"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_close_outside_range_with_warning():
    raw = _make_raw([
        ("20260701", 100, 110, 95, 105, 1000),
        ("20260702", 100, 110, 95, 120, 1000),   # 종가(120) > 고가(110)
    ])
    with pytest.warns(UserWarning, match="종가"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_clean_ohlcv_skips_open_outside_range_with_warning():
    raw = _make_raw([
        ("20260701", 100, 110, 95, 105, 1000),
        ("20260702", 80, 110, 95, 105, 1000),    # 시가(80) < 저가(95)
    ])
    with pytest.warns(UserWarning, match="시가"):
        bars = clean_ohlcv(raw)
    assert len(bars) == 1
    assert bars[0].date == "20260701"


def test_fetch_ohlcv_uses_injected_fetcher_not_real_network():
    raw = _make_raw([("20260701", 100, 110, 95, 105, 1000)])
    bars = fetch_ohlcv("005930", "20260701", "20260701", fetcher=lambda t, s, e: raw)
    assert len(bars) == 1
    assert bars[0].volume == 1000


def test_to_daily_bar_preserves_prices_drops_volume():
    bar = OhlcvBar(date="20260701", open=100, high=110, low=95, close=105, volume=1000)
    db = to_daily_bar(bar)
    assert (db.date, db.open, db.high, db.low, db.close) == ("20260701", 100, 110, 95, 105)


def test_fetch_universe_returns_tickers_when_available():
    result = fetch_universe("20260714", market="KOSPI", fetcher=lambda d, m: ["005930", "000660"])
    assert result == ["005930", "000660"]


def test_fetch_universe_wraps_snapshot_api_failure():
    # 실측(2026-07-14): pykrx get_market_ticker_list가 KRX 서버 응답 변경으로
    # "Expecting value: line 1 column 1 (char 0)" JSONDecodeError를 던짐.
    def broken_fetcher(date, market):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(UniverseUnavailableError):
        fetch_universe("20260714", market="KOSPI", fetcher=broken_fetcher)


def test_fetch_universe_treats_empty_result_as_unavailable():
    with pytest.raises(UniverseUnavailableError):
        fetch_universe("20260714", market="KOSPI", fetcher=lambda d, m: [])
