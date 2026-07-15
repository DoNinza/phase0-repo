from phase0.data.bar_resample import resample_monthly, resample_weekly
from phase0.data.pykrx_ingest import OhlcvBar


def _bar(date, o, h, l, c, v):
    return OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=v)


def test_resample_weekly_empty_input():
    assert resample_weekly([]) == []


def test_resample_weekly_groups_same_iso_week():
    # 2026-07-13(월)~07-17(금)은 같은 ISO 주(2026-W29)
    bars = [
        _bar("20260713", 100, 110, 95, 105, 1000),
        _bar("20260714", 105, 115, 100, 108, 1200),
        _bar("20260717", 108, 120, 106, 118, 900),
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 1
    w = weekly[0]
    assert w.date == "20260717"       # 그 주의 마지막 거래일
    assert w.open == 100              # 그 주 첫날 시가
    assert w.close == 118             # 그 주 마지막날 종가
    assert w.high == 120              # 주간 최고가
    assert w.low == 95                # 주간 최저가
    assert w.volume == 3100           # 주간 거래량 합


def test_resample_weekly_splits_across_week_boundary():
    bars = [
        _bar("20260717", 100, 105, 95, 102, 500),   # 2026-W29 (금)
        _bar("20260720", 102, 108, 100, 106, 600),  # 2026-W30 (월)
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 2
    assert [w.date for w in weekly] == ["20260717", "20260720"]


def test_resample_monthly_groups_same_month():
    bars = [
        _bar("20260701", 100, 105, 95, 102, 500),
        _bar("20260715", 102, 130, 100, 125, 700),
        _bar("20260731", 125, 128, 118, 120, 400),
    ]
    monthly = resample_monthly(bars)
    assert len(monthly) == 1
    m = monthly[0]
    assert m.date == "20260731"
    assert m.open == 100
    assert m.close == 120
    assert m.high == 130
    assert m.low == 95
    assert m.volume == 1600


def test_resample_monthly_splits_across_month_boundary():
    bars = [
        _bar("20260731", 100, 105, 95, 102, 500),
        _bar("20260801", 102, 108, 100, 106, 600),
    ]
    monthly = resample_monthly(bars)
    assert len(monthly) == 2
    assert [m.date for m in monthly] == ["20260731", "20260801"]


def test_resample_handles_unsorted_input():
    bars = [
        _bar("20260714", 105, 115, 100, 108, 1200),
        _bar("20260713", 100, 110, 95, 105, 1000),   # 순서 뒤집힘
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 1
    assert weekly[0].open == 100      # 날짜순 첫날(0713) 시가가 나와야 함
    assert weekly[0].close == 108     # 날짜순 마지막날(0714) 종가
