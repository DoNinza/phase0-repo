"""분봉 축적 저장소 (2026-07-15, STAGE 7 항목 4 재개).

배경: KIS 분봉 API가 "오늘 것만" 제공한다는 게 이미 확인됐다(README, 분봉
검증 Blocker 해소). 과거 분봉을 소급해서 얻을 방법이 없으므로, 매일 자동으로
오늘의 분봉을 저장해나가는 방식으로 우리만의 분봉 데이터셋을 직접 축적한다
— 페이퍼 트레이딩 로그(phase0.paper.trade_log)와 동일한 JSONL append-only
패턴, 종목별 1개 파일.

실측(2026-07-15, 삼성전자 스팟체크)으로 드러난 API 한계: 1회 호출이 전체
장중(약 390분)을 다 주지 않고, FID_INPUT_HOUR_1로 지정한 시각까지의
**최근 30개 봉만** 돌려준다 — 그래서 하루 전체를 모으려면 시각을 30분씩
당겨가며 여러 번 호출해야 한다(scripts/collect_minute_bars.py가 그 처리를
한다). 이 모듈 자체는 저장소 I/O만 담당한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class MinuteBar:
    date: str       # YYYYMMDD
    time: str       # HHMMSS (체결시각)
    open: float
    high: float
    low: float
    close: float
    volume: int


def store_path(base_dir: Path, ticker: str) -> Path:
    return base_dir / f"{ticker}.jsonl"


def existing_dates(path: Path) -> set[str]:
    """이미 저장된 날짜 집합 — 같은 날 재실행 시 중복 수집을 막는 데 쓴다."""
    if not path.exists():
        return set()
    dates = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                dates.add(json.loads(line)["date"])
    return dates


def append_bars(path: Path, bars: list[MinuteBar]) -> None:
    """(date, time) 기준 중복은 걸러내고 append — 시각을 30분씩 당겨가며
    여러 번 호출할 때 경계에서 겹치는 봉이 생길 수 있어서다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_keys = {(b.date, b.time) for b in load_bars(path)}
    with path.open("a", encoding="utf-8") as f:
        for b in bars:
            key = (b.date, b.time)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            f.write(json.dumps(asdict(b), ensure_ascii=False) + "\n")


def load_bars(path: Path) -> list[MinuteBar]:
    if not path.exists():
        return []
    bars = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                bars.append(MinuteBar(**json.loads(line)))
    return bars
