"""일봉 로컬 캐시 (2026-07-16, 대시보드 종목별 차트용).

배경: 대시보드에 종목별 일봉/주봉/월봉 차트를 붙이려면 매 생성마다
pykrx를 라이브 호출하는 대신 로컬에 캐시해두는 게 낫다 — 워치리스트
(KR 기본 20종목 + ETF 기본 15종목)만 해도 매번 수년치를 재요청하면
느리고 KRX 서버에 불필요한 부하를 준다. minute_bar_store.py와 동일한
JSONL append-only 패턴(종목별 1개 파일, 날짜 기준 중복 제거)을 그대로
따른다 — 분봉이 (date,time) 키였다면 일봉은 date 하나가 키다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from phase0.data.pykrx_ingest import OhlcvBar


def store_path(base_dir: Path, ticker: str) -> Path:
    return base_dir / f"{ticker}.jsonl"


def latest_date(path: Path) -> str | None:
    """캐시에 저장된 가장 최근 날짜 — 증분 수집 시 시작일 결정에 쓴다."""
    bars = load_bars(path)
    return bars[-1].date if bars else None


def append_bars(path: Path, bars: list[OhlcvBar]) -> None:
    """date 기준 중복은 걸러내고 append."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_dates = {b.date for b in load_bars(path)}
    with path.open("a", encoding="utf-8") as f:
        for b in bars:
            if b.date in existing_dates:
                continue
            existing_dates.add(b.date)
            f.write(json.dumps(asdict(b), ensure_ascii=False) + "\n")


def load_bars(path: Path) -> list[OhlcvBar]:
    if not path.exists():
        return []
    bars = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                bars.append(OhlcvBar(**json.loads(line)))
    return sorted(bars, key=lambda b: b.date)
