from phase0.data.minute_bar_store import (
    MinuteBar, append_bars, existing_dates, load_bars, store_path,
)


def _bar(date="20260715", time="090100", close=100.0, volume=1000):
    return MinuteBar(date=date, time=time, open=close, high=close, low=close, close=close, volume=volume)


def test_store_path_uses_ticker_as_filename(tmp_path):
    assert store_path(tmp_path, "005930") == tmp_path / "005930.jsonl"


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(time="090100"), _bar(time="090200")])
    bars = load_bars(path)
    assert len(bars) == 2
    assert [b.time for b in bars] == ["090100", "090200"]


def test_load_bars_returns_empty_list_when_file_missing(tmp_path):
    assert load_bars(tmp_path / "missing.jsonl") == []


def test_append_bars_dedupes_against_existing_file(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(time="090100")])
    append_bars(path, [_bar(time="090100"), _bar(time="090200")])   # 090100 중복
    bars = load_bars(path)
    assert len(bars) == 2
    assert [b.time for b in bars] == ["090100", "090200"]


def test_append_bars_dedupes_within_same_batch_file(tmp_path):
    # 30분씩 당겨가며 호출할 때 경계에서 같은 (date,time) 봉이 두 번
    # 들어올 수 있다 — 한 번의 append_bars 호출 안에서도 걸러져야 한다.
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(time="090100"), _bar(time="090100"), _bar(time="090200")])
    bars = load_bars(path)
    assert len(bars) == 2


def test_existing_dates_reflects_stored_dates(tmp_path):
    path = tmp_path / "005930.jsonl"
    append_bars(path, [_bar(date="20260714", time="090100"), _bar(date="20260715", time="090100")])
    assert existing_dates(path) == {"20260714", "20260715"}


def test_existing_dates_empty_when_file_missing(tmp_path):
    assert existing_dates(tmp_path / "missing.jsonl") == set()
