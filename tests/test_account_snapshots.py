from phase0.paper.account_snapshots import (
    AccountSnapshot, append_snapshot, latest_per_date, load_snapshots,
)


def _snap(ts, date, total_eval_amount=1_000_000.0, deposit=500_000.0,
          stock_eval_amount=500_000.0, pnl_amount=0.0):
    return AccountSnapshot(
        ts=ts, date=date, deposit=deposit, stock_eval_amount=stock_eval_amount,
        total_eval_amount=total_eval_amount, pnl_amount=pnl_amount,
    )


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "account_snapshots.jsonl"
    s1 = _snap("2026-07-15T09:00:00", "20260715")
    s2 = _snap("2026-07-15T09:30:00", "20260715", total_eval_amount=1_050_000.0)

    append_snapshot(path, s1)
    append_snapshot(path, s2)

    loaded = load_snapshots(path)
    assert len(loaded) == 2
    assert loaded[0] == s1
    assert loaded[1] == s2


def test_load_snapshots_returns_empty_list_when_file_missing(tmp_path):
    assert load_snapshots(tmp_path / "does_not_exist.jsonl") == []


def test_latest_per_date_collapses_same_day_keeping_latest_by_ts():
    snapshots = [
        _snap("2026-07-15T09:00:00", "20260715", total_eval_amount=1_000_000.0),
        _snap("2026-07-15T10:00:00", "20260715", total_eval_amount=1_200_000.0),
        _snap("2026-07-15T09:30:00", "20260715", total_eval_amount=1_100_000.0),
    ]
    result = latest_per_date(snapshots)
    assert len(result) == 1
    assert result[0].total_eval_amount == 1_200_000.0


def test_latest_per_date_returns_sorted_by_date_ascending():
    snapshots = [
        _snap("2026-07-16T09:00:00", "20260716"),
        _snap("2026-07-14T09:00:00", "20260714"),
        _snap("2026-07-15T09:00:00", "20260715"),
    ]
    result = latest_per_date(snapshots)
    assert [s.date for s in result] == ["20260714", "20260715", "20260716"]


def test_latest_per_date_empty_input_returns_empty_list():
    assert latest_per_date([]) == []
