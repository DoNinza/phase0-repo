import pytest

from phase0.data.candidate_batch import (
    TickerSummary, summarize_bars, run_batch, liquid_candidates,
)
from phase0.data.pykrx_ingest import OhlcvBar


def _bar(date, close, volume):
    return OhlcvBar(date=date, open=close, high=close, low=close, close=close, volume=volume)


def test_summarize_bars_computes_avg_value_and_date_range():
    bars = [_bar("20260701", 100.0, 1000), _bar("20260702", 200.0, 1000)]
    s = summarize_bars("005930", bars)
    assert s.ok
    assert s.n_days == 2
    assert s.start_date == "20260701"
    assert s.end_date == "20260702"
    # (100*1000 + 200*1000) / 2 = 150000
    assert s.avg_daily_value_krw == pytest.approx(150_000)


def test_summarize_bars_empty_is_an_error_not_a_crash():
    s = summarize_bars("005930", [])
    assert not s.ok
    assert s.n_days == 0
    assert s.error is not None


def test_run_batch_isolates_per_ticker_failure():
    def fetch(ticker, start, end):
        if ticker == "BROKEN":
            raise RuntimeError("network hiccup")
        return [_bar("20260701", 100.0, 10)]

    results = run_batch(["005930", "BROKEN", "000660"], "20260701", "20260701", fetch=fetch)
    assert len(results) == 3
    ok_tickers = [r.ticker for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    assert ok_tickers == ["005930", "000660"]
    assert len(failed) == 1
    assert failed[0].ticker == "BROKEN"
    assert "network hiccup" in failed[0].error


def test_run_batch_continues_after_first_failure_and_returns_all():
    # 배치가 첫 실패에서 멈추지 않고 나머지 종목도 전부 시도하는지 확인
    calls = []

    def fetch(ticker, start, end):
        calls.append(ticker)
        if ticker == "A":
            raise RuntimeError("boom")
        return [_bar("20260701", 50.0, 4)]

    results = run_batch(["A", "B", "C"], "20260701", "20260701", fetch=fetch)
    assert calls == ["A", "B", "C"]
    assert len(results) == 3


def test_liquid_candidates_filters_by_threshold():
    summaries = [
        TickerSummary("HIGH", 10, "20260701", "20260710", avg_daily_value_krw=1_000_000),
        TickerSummary("LOW", 10, "20260701", "20260710", avg_daily_value_krw=10),
        TickerSummary("FAILED", 0, None, None, avg_daily_value_krw=None, error="fetch failed"),
    ]
    result = liquid_candidates(summaries, min_avg_value_krw=1_000)
    assert result == ["HIGH"]
