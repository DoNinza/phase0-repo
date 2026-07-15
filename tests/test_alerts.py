import pytest

from phase0.paper.alerts import Alert, append_alert, diff_states, load_alerts


def _state(halt="none", pipelines=None, account_available=True, strategies=None):
    return {
        "halt_status": halt,
        "pipelines": pipelines or {},
        "account_available": account_available,
        "strategies": strategies or {},
    }


def test_first_run_with_empty_prev_returns_no_alerts():
    curr = _state(halt="drawdown_limit", pipelines={"kr": {"is_stale": True, "available": False}},
                   account_available=False, strategies={"kr": {"n_resolved": 500}})
    assert diff_states({}, curr) == []


def test_halt_status_transition_emits_one_alert():
    prev = _state(halt="none")
    curr = _state(halt="drawdown_limit")
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.category == "circuit_breaker"
    assert a.severity == "warn"
    assert "none" in a.message and "drawdown_limit" in a.message
    assert "조정" not in a.message and "권장" not in a.message and "하세요" not in a.message


def test_halt_status_recovery_to_none_is_info():
    prev = _state(halt="drawdown_limit")
    curr = _state(halt="none")
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    assert alerts[0].severity == "info"


def test_halt_status_no_change_emits_nothing():
    prev = _state(halt="none")
    curr = _state(halt="none")
    assert diff_states(prev, curr) == []


def test_pipeline_stale_to_fresh_and_back():
    prev = _state(pipelines={"kr": {"is_stale": True, "available": True, "label": "KR"}})
    curr = _state(pipelines={"kr": {"is_stale": False, "available": True, "label": "KR"}})
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    assert alerts[0].category == "heartbeat"
    assert alerts[0].severity == "info"

    # 반대 방향(신선 -> 지연)
    prev2 = _state(pipelines={"kr": {"is_stale": False, "available": True, "label": "KR"}})
    curr2 = _state(pipelines={"kr": {"is_stale": True, "available": True, "label": "KR"}})
    alerts2 = diff_states(prev2, curr2)
    assert len(alerts2) == 1
    assert alerts2[0].severity == "warn"


def test_pipeline_available_to_unavailable_and_back():
    prev = _state(pipelines={"kr": {"is_stale": False, "available": True}})
    curr = _state(pipelines={"kr": {"is_stale": False, "available": False}})
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    assert alerts[0].category == "heartbeat"
    assert alerts[0].severity == "warn"

    prev2 = _state(pipelines={"kr": {"is_stale": False, "available": False}})
    curr2 = _state(pipelines={"kr": {"is_stale": False, "available": True}})
    alerts2 = diff_states(prev2, curr2)
    assert len(alerts2) == 1
    assert alerts2[0].severity == "info"


def test_pipeline_present_in_curr_not_in_prev_emits_no_alert():
    prev = _state(pipelines={})
    curr = _state(pipelines={"new_pipeline": {"is_stale": True, "available": False}})
    assert diff_states(prev, curr) == []


def test_pipeline_no_change_emits_nothing():
    p = {"is_stale": False, "available": True}
    prev = _state(pipelines={"kr": dict(p)})
    curr = _state(pipelines={"kr": dict(p)})
    assert diff_states(prev, curr) == []


def test_account_available_transition_both_directions():
    prev = _state(account_available=True)
    curr = _state(account_available=False)
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    assert alerts[0].category == "account"
    assert alerts[0].severity == "warn"

    prev2 = _state(account_available=False)
    curr2 = _state(account_available=True)
    alerts2 = diff_states(prev2, curr2)
    assert len(alerts2) == 1
    assert alerts2[0].severity == "info"


def test_account_available_no_change_emits_nothing():
    prev = _state(account_available=True)
    curr = _state(account_available=True)
    assert diff_states(prev, curr) == []


@pytest.mark.parametrize("milestone", [50, 100, 500, 1000])
def test_each_sample_size_milestone_crossed(milestone):
    prev = _state(strategies={"kr": {"n_resolved": milestone - 1, "label": "GDR-KR"}})
    curr = _state(strategies={"kr": {"n_resolved": milestone, "label": "GDR-KR"}})
    alerts = diff_states(prev, curr)
    assert len(alerts) == 1
    assert alerts[0].category == "sample_size"
    assert alerts[0].severity == "info"
    assert str(milestone) in alerts[0].message


def test_multi_milestone_jump_emits_one_alert_per_milestone_crossed():
    prev = _state(strategies={"kr": {"n_resolved": 10, "label": "GDR-KR"}})
    curr = _state(strategies={"kr": {"n_resolved": 150, "label": "GDR-KR"}})
    alerts = diff_states(prev, curr)
    assert len(alerts) == 2
    messages = " ".join(a.message for a in alerts)
    assert "50" in messages and "100" in messages


def test_sample_size_no_milestone_crossed_emits_nothing():
    prev = _state(strategies={"kr": {"n_resolved": 40, "label": "GDR-KR"}})
    curr = _state(strategies={"kr": {"n_resolved": 49, "label": "GDR-KR"}})
    assert diff_states(prev, curr) == []


def test_append_and_load_roundtrip(tmp_path):
    path = tmp_path / "alerts.jsonl"
    a1 = Alert(ts="2026-07-15T09:00:00", severity="warn", category="circuit_breaker",
               message="서킷브레이커 상태가 none → drawdown_limit로 전환")
    a2 = Alert(ts="2026-07-15T09:30:00", severity="info", category="sample_size",
               message="전략 'GDR-KR' 해소 거래 수가 50건에 도달")

    append_alert(path, a1)
    append_alert(path, a2)

    loaded = load_alerts(path)
    assert loaded == [a1, a2]


def test_load_alerts_returns_empty_list_when_file_missing(tmp_path):
    assert load_alerts(tmp_path / "does_not_exist.jsonl") == []
