import pytest

import scripts.generate_dashboard as gd
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
