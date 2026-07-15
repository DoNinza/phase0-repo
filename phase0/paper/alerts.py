"""상태전환 알림(B5) — 사실만 기록, 추천/제안은 절대 하지 않는다.

배경(README "메타 감사"의 anti-p-hacking 원칙 계승): 이 프로젝트는 사전등록된
파라미터를 결과 보고 조정하지 않고, 대시보드도 파라미터·전략 변경을 절대
"추천"하지 않는다. 이 모듈이 만드는 알림 문구도 같은 규율을 따른다 — 예를
들어 "서킷브레이커 상태가 none → drawdown_limit로 전환"은 사실 서술이라
괜찮지만 "임계값을 조정하세요" 같은 제안은 이 모듈이 만드는 어떤 메시지에도
등장해서는 안 된다.

trade_log.py/account_snapshots.py와 동일한 JSONL append-only 패턴(append/
load 쌍, 중앙 DB 없음)을 그대로 따른다. diff_states()는 이 파일에서 유일하게
I/O가 없는 순수 함수 — "이전 상태 dict"와 "현재 상태 dict"를 비교해 상태전환
알림 목록만 만든다(실제 이전 상태를 어디서 읽어오고 새 알림을 어디에
append하는지는 scripts/generate_dashboard.py의 몫).

첫 실행(prev == {})은 무조건 빈 목록을 반환한다 — 비교 대상이 없는데 현재
상태 전부를 "새로 전환됨"으로 취급하면 알림 로그가 첫 실행부터 홍수가 된다.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

# 해소 거래 수 마일스톤 — 표본 크기가 늘어나는 것 자체는 사실이라 알릴 가치가
# 있지만(위험지표의 "표본부족" 판정이 언제 풀리는지와도 맞닿아 있음), 매
# 거래마다 알리면 소음이 되므로 몇 개 지점에서만 끊는다.
SAMPLE_SIZE_MILESTONES = (50, 100, 500, 1000)


@dataclass
class Alert:
    ts: str            # ISO 타임스탬프(초단위) — 알림이 발생(감지)한 시각
    severity: str       # "info" | "warn"
    category: str       # "circuit_breaker" | "heartbeat" | "account" | "sample_size"
    message: str        # 사실 서술 문장(한국어) — 추천/제안 문구 금지


def append_alert(path: Path, alert: Alert) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(alert), ensure_ascii=False) + "\n")


def load_alerts(path: Path) -> list[Alert]:
    if not path.exists():
        return []
    alerts = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                alerts.append(Alert(**json.loads(line)))
    return alerts


def _now_ts() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _pipeline_transition_alerts(ts: str, prev_pipelines: dict, curr_pipelines: dict) -> list[Alert]:
    """파이프라인별 하트비트 신선도(is_stale)·가동여부(available) 전환.

    curr에는 있는데 prev에는 아직 없는 파이프라인 키(예: 새로 추가된
    파이프라인)는 "전환"이라 부를 이전 상태 자체가 없으므로 건너뛴다 —
    비교 불가를 임의로 True/False 어느 쪽으로도 채워 넣지 않는다.
    """
    alerts = []
    for key, curr_p in curr_pipelines.items():
        if key not in prev_pipelines:
            continue
        prev_p = prev_pipelines[key]
        label = curr_p.get("label", key)

        prev_stale, curr_stale = prev_p.get("is_stale"), curr_p.get("is_stale")
        if prev_stale != curr_stale:
            direction = "정상 → 지연" if curr_stale else "지연 → 정상"
            severity = "warn" if curr_stale else "info"
            alerts.append(Alert(
                ts=ts, severity=severity, category="heartbeat",
                message=f"파이프라인 '{label}' 하트비트 상태가 {direction}(으)로 전환",
            ))

        prev_avail, curr_avail = prev_p.get("available"), curr_p.get("available")
        if prev_avail != curr_avail:
            direction = "가동 → 미가동" if not curr_avail else "미가동 → 가동"
            severity = "warn" if not curr_avail else "info"
            alerts.append(Alert(
                ts=ts, severity=severity, category="heartbeat",
                message=f"파이프라인 '{label}' 상태가 {direction}(으)로 전환",
            ))
    return alerts


def _sample_size_alerts(ts: str, prev_strategies: dict, curr_strategies: dict) -> list[Alert]:
    """전략별 해소 거래 수(n_resolved) 마일스톤 통과.

    prev에 해당 전략 키가 아직 없으면(새 전략 추가 등) 0으로 취급한다 —
    파이프라인 쪽과 달리 여기서는 "건너뛰기"가 아니라 "0에서 출발"이 맞는
    처리다: 표본이 이미 쌓여 있는데 그 사실을 영원히 알리지 않는 쪽보다,
    한 번은 마일스톤 알림이 뒤늦게라도 뜨는 쪽이 더 정직하기 때문.
    """
    alerts = []
    for key, curr_s in curr_strategies.items():
        prev_n = prev_strategies.get(key, {}).get("n_resolved", 0)
        curr_n = curr_s.get("n_resolved", 0)
        label = curr_s.get("label", key)
        for milestone in SAMPLE_SIZE_MILESTONES:
            if prev_n < milestone <= curr_n:
                alerts.append(Alert(
                    ts=ts, severity="info", category="sample_size",
                    message=f"전략 '{label}' 해소 거래 수가 {milestone}건에 도달",
                ))
    return alerts


def diff_states(prev: dict, curr: dict) -> list[Alert]:
    """이전/현재 상태 dict를 비교해 사실 기반 알림 목록을 만든다(순수 함수, I/O 없음).

    기대하는 dict 모양(scripts/generate_dashboard.py의 _state_summary() 참고):
        {
            "halt_status": str,
            "pipelines": {key: {"is_stale": bool, "available": bool, "label": str}},
            "account_available": bool,
            "strategies": {key: {"n_resolved": int, "label": str}},
        }

    prev == {} (상태 파일이 아직 없던 첫 실행)이면 무조건 빈 목록 — 비교
    대상이 없는 상태에서 현재값 전체를 "전환됨"으로 알리면 알림 로그가
    첫 실행부터 홍수가 된다.
    """
    if not prev:
        return []

    ts = _now_ts()
    alerts: list[Alert] = []

    prev_halt = prev.get("halt_status")
    curr_halt = curr.get("halt_status")
    if prev_halt is not None and curr_halt is not None and prev_halt != curr_halt:
        severity = "info" if curr_halt == "none" else "warn"
        alerts.append(Alert(
            ts=ts, severity=severity, category="circuit_breaker",
            message=f"서킷브레이커 상태가 {prev_halt} → {curr_halt}로 전환",
        ))

    alerts.extend(_pipeline_transition_alerts(
        ts, prev.get("pipelines", {}), curr.get("pipelines", {}),
    ))

    prev_acct = prev.get("account_available")
    curr_acct = curr.get("account_available")
    if prev_acct is not None and curr_acct is not None and prev_acct != curr_acct:
        direction = "가능 → 불가" if not curr_acct else "불가 → 가능"
        severity = "warn" if not curr_acct else "info"
        alerts.append(Alert(
            ts=ts, severity=severity, category="account",
            message=f"실계좌 조회 가능 여부가 {direction}로 전환",
        ))

    alerts.extend(_sample_size_alerts(
        ts, prev.get("strategies", {}), curr.get("strategies", {}),
    ))

    return alerts
