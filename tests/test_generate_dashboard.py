import datetime as dt
import json

import pytest

import scripts.generate_dashboard as gd
from phase0.data.daily_bar_store import append_bars as append_index_bars, store_path as index_store_path
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.paper.account_snapshots import AccountSnapshot, append_snapshot
from phase0.paper.alerts import Alert, append_alert
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


def test_build_alerts_handles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "ALERTS_LOG_PATH", tmp_path / "does_not_exist.jsonl")

    alerts = gd.build_alerts()
    assert alerts["alerts"] == []
    assert alerts["n_total"] == 0


def test_build_alerts_respects_embedded_limit(tmp_path, monkeypatch):
    alerts_path = tmp_path / "alerts.jsonl"
    monkeypatch.setattr(gd, "ALERTS_LOG_PATH", alerts_path)
    monkeypatch.setattr(gd, "ALERTS_EMBEDDED_LIMIT", 5)

    for i in range(1, 11):   # 10건, 한도(5)보다 많음
        append_alert(alerts_path, Alert(
            ts=f"2026-07-{i:02d}T09:00:00", severity="info", category="sample_size",
            message=f"전략 'GDR-KR' 해소 거래 수가 {i}건에 도달",
        ))

    alerts = gd.build_alerts()
    assert alerts["n_total"] == 10
    assert len(alerts["alerts"]) == 5
    # 한도를 넘으면 가장 최근 것들만 남아야 한다(과거가 아니라 최신을 유지)
    assert alerts["alerts"][-1]["ts"] == "2026-07-10T09:00:00"
    assert alerts["alerts"][0]["ts"] == "2026-07-06T09:00:00"


def test_state_summary_extracts_minimal_diff_input(tmp_path):
    payload = {
        "halt_status": "drawdown_limit",
        "system_health": {"pipelines": [
            {"key": "kr", "label": "GDR-KR 파이프라인", "is_stale": True, "available": False},
        ]},
        "account": {"available": True},
        "strategy_data": {"strategies": [
            {"key": "kr", "label": "GDR-KR", "n_resolved": 42},
        ]},
    }
    summary = gd._state_summary(payload)
    assert summary == {
        "halt_status": "drawdown_limit",
        "pipelines": {"kr": {"is_stale": True, "available": False, "label": "GDR-KR 파이프라인"}},
        "account_available": True,
        "strategies": {"kr": {"n_resolved": 42, "label": "GDR-KR"}},
    }


def test_read_last_nonempty_line_across_chunk_boundary(tmp_path):
    # chunk_size를 작게 줘서 "여러 청크를 거슬러 올라가야 줄바꿈을 찾는"
    # 경로(긴 줄 하나짜리 파일 등)도 죽지 않고 동작하는지 확인.
    f = tmp_path / "big.jsonl"
    f.write_text('{"date": "20260101"}\n' + ("x" * 50) + '\n{"date": "20260228"}\n', encoding="utf-8")
    assert gd._read_last_nonempty_line(f, chunk_size=8) == '{"date": "20260228"}'


# ---- B7: 사전 등록 백테스트 결과 탭 — 정적 데이터라 구조만 가볍게 확인한다 ----

def test_build_backtest_results_returns_nonempty_well_formed_structure():
    payload = gd.build_backtest_results()
    result_sets = payload["result_sets"]
    assert len(result_sets) > 0

    expected_keys = {
        "key", "title", "strategy", "universe", "period", "columns",
        "rows", "conclusion", "source", "date", "incomplete_note",
    }
    seen_keys = []
    for rs in result_sets:
        assert expected_keys.issubset(rs.keys())
        assert rs["key"]
        seen_keys.append(rs["key"])
        assert isinstance(rs["columns"], list) and rs["columns"]
        assert isinstance(rs["rows"], list) and rs["rows"]
        for row in rs["rows"]:
            assert set(row.keys()) == {"cells", "verdict", "verdict_detail", "best"}
            # 판정이 없는 표(ML 필터 OOS)를 제외하면, 값이 있을 때는
            # README가 실제로 쓴 두 판정 토큰 중 하나여야 한다(재작문 금지 확인).
            if row["verdict"]:
                assert row["verdict"] in {"reject", "insufficient_sample"}
            assert len(row["cells"]) == len(rs["columns"])

    # key는 대시보드 JS가 없어도 그 자체로 유일해야 나중에 뒤섞이지 않는다.
    assert len(seen_keys) == len(set(seen_keys))


def test_build_backtest_results_is_json_serializable():
    payload = gd.build_backtest_results()
    encoded = json.dumps(payload, ensure_ascii=False)
    assert len(encoded) > 0
    # 소수점 재계산 없는 정적 문자열 데이터라 다시 파싱해도 원본과 동일해야 한다.
    assert json.loads(encoded) == payload


# ---- B1: 지수 스트립 — 캐시 없음/인증정보 없음도 죽지 않아야 하고, 캐시가
# 있으면 스파크라인이 최근 N개만 오래된 순으로 잘려야 한다. 라이브 KIS 호출은
# load_credentials()가 CredentialsMissingError를 던지도록 monkeypatch해
# 네트워크 없이도 결정적으로 검증한다(build_account_status와 동일하게 이
# 프로젝트는 KIS 라이브 호출 자체를 직접 pytest하지 않는다).

def test_build_index_strip_missing_cache_and_no_credentials_reports_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "INDEX_BARS_DIR", tmp_path / "index_bars_missing")

    def _raise_missing_creds():
        raise gd.CredentialsMissingError("테스트: 인증정보 없음")
    monkeypatch.setattr(gd, "load_credentials", _raise_missing_creds)

    strip = gd.build_index_strip()
    indices = strip["indices"]
    assert {i["key"] for i in indices} == {"kospi", "kosdaq", "kospi200"}
    for idx in indices:
        assert idx["live_available"] is False
        assert idx["current"] is None
        assert idx["change_pct"] is None
        assert idx["sparkline_closes"] == []
        assert idx["as_of"] is None


def test_build_index_strip_seeded_cache_caps_and_orders_sparkline(tmp_path, monkeypatch):
    index_dir = tmp_path / "index_bars"
    monkeypatch.setattr(gd, "INDEX_BARS_DIR", index_dir)
    monkeypatch.setattr(gd, "INDEX_STRIP_SPARKLINE_LIMIT", 5)

    def _raise_missing_creds():
        raise gd.CredentialsMissingError("테스트: 인증정보 없음")
    monkeypatch.setattr(gd, "load_credentials", _raise_missing_creds)

    bars = [
        OhlcvBar(date=f"202607{d:02d}", open=100.0 + d, high=101.0 + d, low=99.0 + d,
                 close=100.0 + d, volume=1000)
        for d in range(1, 11)   # 20260701..20260710, 한도(5)보다 많은 10봉
    ]
    append_index_bars(index_store_path(index_dir, "kospi"), bars)

    strip = gd.build_index_strip()
    by_key = {i["key"]: i for i in strip["indices"]}

    kospi = by_key["kospi"]
    # 마지막 5개, 오래된 날짜 -> 최신 날짜 순(20260706~20260710의 종가)
    assert kospi["sparkline_closes"] == [106.0, 107.0, 108.0, 109.0, 110.0]
    assert kospi["as_of"] == "20260710"
    assert kospi["live_available"] is False
    assert kospi["current"] is None

    # 캐시가 아예 없는 지수는 죽지 않고 빈 스파크라인으로 보고되어야 한다.
    assert by_key["kosdaq"]["sparkline_closes"] == []
    assert by_key["kosdaq"]["as_of"] is None
    assert by_key["kospi200"]["sparkline_closes"] == []
