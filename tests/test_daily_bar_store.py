from phase0.data.daily_bar_store import append_bars, latest_date, load_bars, store_path
from phase0.data.pykrx_ingest import OhlcvBar


def _bar(date="20260714", close=100.0, volume=1000):
    return OhlcvBar(date=date, open=close, high=close, low=close, close=close, volume=volume)


def test_store_path_uses_ticker_as_filename(tmp_path):
    assert store_path(tmp_path, "005930") == tmp_path / "005930.jsonl"


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(date="20260714"), _bar(date="20260715")])
    bars = load_bars(path)
    assert [b.date for b in bars] == ["20260714", "20260715"]


def test_load_bars_returns_empty_list_when_file_missing(tmp_path):
    assert load_bars(tmp_path / "missing.jsonl") == []


def test_append_bars_dedupes_by_date(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(date="20260714", close=100.0)])
    append_bars(path, [_bar(date="20260714", close=999.0), _bar(date="20260715", close=101.0)])
    bars = load_bars(path)
    assert [b.date for b in bars] == ["20260714", "20260715"]
    assert bars[0].close == 100.0   # 먼저 저장된 값 유지, 나중 값으로 덮어쓰지 않음


def test_load_bars_returns_sorted_by_date(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(date="20260715"), _bar(date="20260714")])
    bars = load_bars(path)
    assert [b.date for b in bars] == ["20260714", "20260715"]


def test_latest_date_returns_none_when_empty(tmp_path):
    assert latest_date(tmp_path / "missing.jsonl") is None


def test_latest_date_returns_most_recent(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(date="20260714"), _bar(date="20260715")])
    assert latest_date(path) == "20260715"
