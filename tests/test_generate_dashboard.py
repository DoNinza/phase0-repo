import datetime as dt
import json

import pytest

import scripts.generate_dashboard as gd
from phase0.paper.account_snapshots import AccountSnapshot, append_snapshot
from phase0.paper.trade_log import PaperEntry, append_entry


@pytest.mark.parametrize("raw,expected", [
    ("12345", 12345.0),
    ("-3.5", -3.5),
    ("", 0.0),
    (None, 0.0),
    ("abc", 0.0),
])
def test_to_float_handles_empty_and_invalid_kis_fields(raw, expected):
    assert gd._to_float(raw) == expected


def _entry(date, pnl_pct, resolution="target_hit", ticker="005930"):
    return PaperEntry(ticker=ticker, date=date, entry_price=100.0, target_price=105.0,
                       stop_price=97.0, shares=10, resolution=resolution, pnl_pct=pnl_pct)


def test_build_strategy_data_aggregates_per_strategy_and_tags_trades(tmp_path, monkeypatch):
    kr_log = tmp_path / "kr.jsonl"
    etf_log = tmp_path / "etf.jsonl"
    append_entry(kr_log, _entry("20260701", 0.02))
    append_entry(kr_log, PaperEntry(ticker="000660", date="20260702", entry_price=100.0,
                                     target_price=105.0, stop_price=97.0, shares=5))  # 미결
    append_entry(etf_log, _entry("20260701", -0.01, resolution="stop_hit", ticker="069500"))

    monkeypatch.setattr(gd, "STRATEGIES", [
        {"key": "kr", "label": "GDR-KR", "log_path": kr_log, "config_note": "test"},
        {"key": "etf", "label": "GDR-ETF", "log_path": etf_log, "config_note": "test"},
    ])

    data = gd.build_strategy_data()
    by_key = {s["key"]: s for s in data["strategies"]}
    assert by_key["kr"]["n_resolved"] == 1
    assert by_key["kr"]["n_pending"] == 1
    assert by_key["etf"]["n_resolved"] == 1
    assert len(data["resolved_trades"]) == 2
    assert {t["strategy"] for t in data["resolved_trades"]} == {"kr", "etf"}


def test_build_risk_metrics_insufficient_sample_returns_none(tmp_path, monkeypatch):
    kr_log = tmp_path / "kr.jsonl"
    append_entry(kr_log, _entry("20260701", 0.01))
    monkeypatch.setattr(gd, "STRATEGIES", [
        {"key": "kr", "label": "GDR-KR", "log_path": kr_log, "config_note": "test"},
    ])

    rm = gd.build_risk_metrics()
    assert rm["n_trading_days"] == 1
    assert rm["sharpe"] is None
    assert rm["sortino"] is None
    assert rm["var95_pct"] is None
    assert rm["bootstrap_ci"] is None


def _snapshot(date, ts=None, total_eval_amount=1_000_000.0):
    return AccountSnapshot(
        ts=ts or f"{date[:4]}-{date[4:6]}-{date[6:8]}T09:00:00",
        date=date, deposit=500_000.0, stock_eval_amount=500_000.0,
        total_eval_amount=total_eval_amount, pnl_amount=0.0,
    )


def test_build_equity_curve_handles_missing_snapshots_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "ACCOUNT_SNAPSHOTS_PATH", tmp_path / "does_not_exist.jsonl")

    curve = gd.build_equity_curve()
    assert curve["points"] == []
    assert curve["n_total_snapshots"] == 0


def test_build_equity_curve_respects_embedded_limit(tmp_path, monkeypatch):
    snapshots_path = tmp_path / "account_snapshots.jsonl"
    monkeypatch.setattr(gd, "ACCOUNT_SNAPSHOTS_PATH", snapshots_path)
    monkeypatch.setattr(gd, "EQUITY_CURVE_EMBEDDED_LIMIT", 5)

    for day in range(1, 11):   # 10일치, 한도(5)보다 많음
        append_snapshot(snapshots_path, _snapshot(f"202607{day:02d}"))

    curve = gd.build_equity_curve()
    assert curve["n_total_snapshots"] == 10
    assert len(curve["points"]) == 5
    # 한도를 넘으면 가장 최근 것들만 남아야 한다(과거가 아니라 최신을 유지)
    assert curve["points"][-1]["date"] == "20260710"
    assert curve["points"][0]["date"] == "20260706"


def test_build_system_health_reports_missing_dir_as_unavailable(tmp_path, monkeypatch):
    missing_dir = tmp_path / "does_not_exist_yet"
    monkeypatch.setattr(gd, "SYSTEM_HEALTH_PIPELINES", [
        {"key": "ghost", "label": "미가동 파이프라인",
         "dir_path": missing_dir, "heartbeat_path": missing_dir / "heartbeat.txt"},
    ])

    health = gd.build_system_health()
    assert len(health["pipelines"]) == 1
    p = health["pipelines"][0]
    assert p["available"] is False
    assert p["heartbeat"] is None
    assert p["file_count"] == 0
    assert p["latest_date"] is None
    assert p["dir_size_bytes"] == 0
    assert p["is_stale"] is True   # 미가동은 신선할 수 없다


def test_build_system_health_computes_freshness_and_latest_date(tmp_path, monkeypatch):
    pipeline_dir = tmp_path / "fake_pipeline"
    pipeline_dir.mkdir()

    # 종목 2개, 각각 여러 줄 — 마지막 줄의 date만 봐야 한다(load_bars 전체
    # 파싱 없이 last-line만 읽는지 확인).
    (pipeline_dir / "AAA.jsonl").write_text(
        "\n".join(json.dumps({"date": d, "time": "090000", "open": 1, "high": 1,
                               "low": 1, "close": 1, "volume": 1})
                  for d in ["20260710", "20260711", "20260712"]) + "\n",
        encoding="utf-8",
    )
    (pipeline_dir / "BBB.jsonl").write_text(
        "\n".join(json.dumps({"date": d, "time": "090000", "open": 1, "high": 1,
                               "low": 1, "close": 1, "volume": 1})
                  for d in ["20260701", "20260714"]) + "\n",
        encoding="utf-8",
    )

    heartbeat_path = pipeline_dir / "heartbeat.txt"
    fresh_ts = (dt.datetime.now() - dt.timedelta(hours=2)).isoformat()
    heartbeat_path.write_text(fresh_ts, encoding="utf-8")

    monkeypatch.setattr(gd, "SYSTEM_HEALTH_PIPELINES", [
        {"key": "fake", "label": "가짜 파이프라인",
         "dir_path": pipeline_dir, "heartbeat_path": heartbeat_path},
    ])

    health = gd.build_system_health()
    p = health["pipelines"][0]
    assert p["available"] is True
    assert p["file_count"] == 2
    assert p["latest_date"] == "20260714"   # 두 파일의 마지막 줄 중 최신
    assert p["heartbeat"] == fresh_ts
    assert p["heartbeat_age_hours"] == pytest.approx(2.0, abs=0.05)
    assert p["is_stale"] is False   # 2시간 전 < 96시간 임계값
    assert p["dir_size_bytes"] > 0


def test_build_system_health_stale_heartbeat_flagged(tmp_path, monkeypatch):
    pipeline_dir = tmp_path / "stale_pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "AAA.jsonl").write_text(
        json.dumps({"date": "20260601", "time": "090000", "open": 1, "high": 1,
                     "low": 1, "close": 1, "volume": 1}) + "\n",
        encoding="utf-8",
    )
    heartbeat_path = pipeline_dir / "heartbeat.txt"
    old_ts = (dt.datetime.now() - dt.timedelta(hours=200)).isoformat()
    heartbeat_path.write_text(old_ts, encoding="utf-8")

    monkeypatch.setattr(gd, "SYSTEM_HEALTH_PIPELINES", [
        {"key": "stale", "label": "오래된 파이프라인",
         "dir_path": pipeline_dir, "heartbeat_path": heartbeat_path},
    ])

    health = gd.build_system_health()
    p = health["pipelines"][0]
    assert p["is_stale"] is True   # 200시간 전 > 96시간 임계값


def test_read_last_nonempty_line_handles_small_and_missing_files(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert gd._read_last_nonempty_line(empty) is None
    assert gd._read_last_nonempty_line(tmp_path / "nope.jsonl") is None

    f = tmp_path / "small.jsonl"
    f.write_text('{"date": "20260101"}\n{"date": "20260102"}\n', encoding="utf-8")
    assert gd._read_last_nonempty_line(f) == '{"date": "20260102"}'


def test_read_last_nonempty_line_across_chunk_boundary(tmp_path):
    # chunk_size를 작게 줘서 "여러 청크를 거슬러 올라가야 줄바꿈을 찾는"
    # 경로(긴 줄 하나짜리 파일 등)도 죽지 않고 동작하는지 확인.
    f = tmp_path / "big.jsonl"
    f.write_text('{"date": "20260101"}\n' + ("x" * 50) + '\n{"date": "20260228"}\n', encoding="utf-8")
    assert gd._read_last_nonempty_line(f, chunk_size=8) == '{"date": "20260228"}'
