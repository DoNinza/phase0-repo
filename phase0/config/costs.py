"""costs.yaml 로더.

원칙(기획안 §5.5): 비용은 하드코딩 금지, 설정파일 관리, 기준일 필수 기재.
이 모듈은 costs.yaml을 읽어 Base 왕복비용과 시나리오별(Optimistic/Base/
Conservative/Stress) 비용을 계산해서 돌려준다. 조건부 항목(손절 시장가 추가분,
유관기관 제비용)은 Base 합산에서 의도적으로 제외한다 — 각각 표8·향후 실측
반영 전용이기 때문이다.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_COSTS_PATH = Path(__file__).with_name("costs.yaml")


@dataclass
class CostBreakdown:
    base_total: float
    components: dict[str, float]
    unresolved: list[str]           # tag == "외부 확인 필요" 인 항목 이름들
    last_verified: str
    next_review_due: str

    def is_stale(self, today: _dt.date | None = None) -> bool:
        """next_review_due가 지났으면 True — 세법 연 1회 확인 일정(§1.9)이 밀렸다는 신호."""
        today = today or _dt.date.today()
        due = _dt.date.fromisoformat(self.next_review_due)
        return today >= due


def load_raw(path: Path = DEFAULT_COSTS_PATH) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def base_breakdown(path: Path = DEFAULT_COSTS_PATH) -> CostBreakdown:
    raw = load_raw(path)
    comps = raw["components"]
    values = {name: c["value"] for name, c in comps.items()}
    unresolved = [name for name, c in comps.items() if c.get("tag") == "외부 확인 필요"]
    return CostBreakdown(
        base_total=sum(values.values()),
        components=values,
        unresolved=unresolved,
        last_verified=raw["meta"]["last_verified"],
        next_review_due=raw["meta"]["next_review_due"],
    )


def scenario_costs(path: Path = DEFAULT_COSTS_PATH) -> list[tuple[str, float]]:
    """표4용 (이름, C) 리스트. 표시 이름은 기존 문서 표기와 맞춘다."""
    raw = load_raw(path)
    base = base_breakdown(path).base_total
    sc = raw["scenarios"]

    out = []
    if "optimistic" in sc:
        out.append(("Optimistic(참고용, 판정 사용 금지)", sc["optimistic"]["override_total"]))
    if "base" in sc:
        out.append(("Base 2026(세0.20)", base * sc["base"]["multiplier"]))
    if "conservative" in sc:
        out.append(("Conservative(1.3x)", base * sc["conservative"]["multiplier"]))
    if "stress" in sc:
        out.append(("Stress(2x)", base * sc["stress"]["multiplier"]))
    return out


def conditional_value(name: str, path: Path = DEFAULT_COSTS_PATH) -> float:
    """stoploss_market_extra 등 Base 합산에서 제외된 조건부 비용 항목 조회 (표8용)."""
    raw = load_raw(path)
    return raw["conditional"][name]["value"]


def unresolved_report(path: Path = DEFAULT_COSTS_PATH) -> str:
    """Phase 0 Blocker 해소 현황을 사람이 읽을 수 있는 문자열로 리포트."""
    bd = base_breakdown(path)
    lines = [f"Base 왕복비용 = {bd.base_total * 100:.2f}% (기준일 {bd.last_verified})"]
    if bd.unresolved:
        lines.append("미확정(외부 확인 필요) 항목: " + ", ".join(bd.unresolved))
        lines.append("→ Phase 0 Blocker 미해소 상태 — 이 값이 확정되기 전까지 Base는 잠정치.")
    else:
        lines.append("모든 구성 항목 확정됨.")
    if bd.is_stale():
        lines.append(f"경고: 세법 재확인 예정일({bd.next_review_due})이 지났습니다 — costs.yaml 갱신 필요.")
    return "\n".join(lines)
