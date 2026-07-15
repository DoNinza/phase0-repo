"""실계좌 잔고 스냅샷(JSONL) — 자산 곡선(B4)용 진짜 데이터 축적.

배경: 대시보드는 매 생성마다 KIS 잔고조회(읽기 전용)로 실계좌 총평가금액을
이미 얻는다(generate_dashboard.build_account_status) — 그런데 그 값을
그 순간에만 화면에 찍고 버리면, 시간에 따른 자산 곡선을 그릴 방법이 없다.
이 모듈은 "앞으로 매번 생성될 때마다" 한 스냅샷씩 append해 축적하는
장치다 — trade_log.py와 동일한 JSONL append-only 패턴(중앙 DB 없음).

과거로 소급 채울 수 없는 데이터라 하루라도 늦게 시작하면 그만큼 영원히
빈 구간으로 남는다. 대시보드 생성은 장중 30분 간격으로 하루 여러 번
돌기 때문에(cron) 같은 날짜에 스냅샷이 여러 개 쌓인다 — 곡선을 그릴 때는
latest_per_date()로 그날의 마지막 값만 남겨 하루 1점으로 축약한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AccountSnapshot:
    ts: str                    # ISO 타임스탬프(초단위), 생성 시각
    date: str                  # YYYYMMDD
    deposit: float
    stock_eval_amount: float
    total_eval_amount: float
    pnl_amount: float


def append_snapshot(path: Path, snapshot: AccountSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(snapshot), ensure_ascii=False) + "\n")


def load_snapshots(path: Path) -> list[AccountSnapshot]:
    if not path.exists():
        return []
    snapshots = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                snapshots.append(AccountSnapshot(**json.loads(line)))
    return snapshots


def latest_per_date(snapshots: list[AccountSnapshot]) -> list[AccountSnapshot]:
    """하루 여러 번 쌓인 스냅샷 중 날짜별 마지막 값만 남긴다(순수 함수, I/O 없음).

    ts 기준 정렬 후 날짜별로 마지막 occurrence를 취해 date 오름차순으로 반환.
    """
    by_date: dict[str, AccountSnapshot] = {}
    for s in sorted(snapshots, key=lambda s: s.ts):
        by_date[s.date] = s
    return [by_date[d] for d in sorted(by_date)]
