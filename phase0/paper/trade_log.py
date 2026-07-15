"""페이퍼 트레이딩 거래 로그(JSONL) — 실거래 없이 신호·가상 체결만 기록.

배경(README "메타 감사" 참고): 지금까지 4개 규칙기반 전략은 10년치 과거
데이터 전체로 판정했고 진짜 홀드아웃이 없었다 — 같은 데이터셋에 다섯 번째
가설을 또 물어보는 건 근거가 약해진다. 이 모듈은 "앞으로 실제로 쌓일" 새
데이터를 한 번도 안 본 진짜 홀드아웃으로 축적하기 위한 장치다. 절대 실제
주문을 내지 않는다 — 신호와 가상 체결(장 마감 후 실제 고가/저가/종가로
resolve)만 기록한다.

단순화(정직하게 명시): daily/weekly/monthly_return은 자본 복리·동시보유
포지션을 반영한 진짜 계좌 수익률이 아니라, 그 기간에 청산된 거래들의
pnl_pct 단순평균이다 — circuit_breaker.check_halt()에 넣을 근사치일 뿐,
phase0.bootstrap.cluster_bootstrap의 계좌 지표(CAGR/MDD)와는 다른 것이다.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PaperEntry:
    ticker: str
    date: str                      # YYYYMMDD, 진입일(=청산일, 당일청산)
    entry_price: float
    target_price: float
    stop_price: float
    shares: int
    resolution: str | None = None  # None(미결) | target_hit | stop_hit | ambiguous | close_exit
    pnl_pct: float | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolution is not None


def append_entry(log_path: Path, entry: PaperEntry) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def load_entries(log_path: Path) -> list[PaperEntry]:
    if not log_path.exists():
        return []
    entries = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(PaperEntry(**json.loads(line)))
    return entries


def rewrite_all(log_path: Path, entries: list[PaperEntry]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")


def _resolved(entries: list[PaperEntry]) -> list[PaperEntry]:
    return [e for e in entries if e.is_resolved]


def daily_return(entries: list[PaperEntry], date: str) -> float:
    """그날 청산된 거래들의 pnl_pct 단순평균(근사치, 위 docstring 참고)."""
    day_trades = [e for e in _resolved(entries) if e.date == date]
    if not day_trades:
        return 0.0
    return sum(e.pnl_pct for e in day_trades) / len(day_trades)


def weekly_return(entries: list[PaperEntry], as_of_date: str) -> float:
    as_of = dt.datetime.strptime(as_of_date, "%Y%m%d")
    week_start = (as_of - dt.timedelta(days=as_of.weekday())).strftime("%Y%m%d")
    week_trades = [e for e in _resolved(entries) if week_start <= e.date <= as_of_date]
    if not week_trades:
        return 0.0
    return sum(e.pnl_pct for e in week_trades) / len(week_trades)


def monthly_return(entries: list[PaperEntry], as_of_date: str) -> float:
    month_prefix = as_of_date[:6]
    month_trades = [e for e in _resolved(entries) if e.date[:6] == month_prefix and e.date <= as_of_date]
    if not month_trades:
        return 0.0
    return sum(e.pnl_pct for e in month_trades) / len(month_trades)


def current_drawdown(entries: list[PaperEntry]) -> float:
    """해소된 거래의 누적 pnl%(단순합) 경로에서 고점 대비 현재 낙폭(peak-to-trough).

    circuit_breaker.check_halt()의 current_drawdown_pct 입력용. 0 이하 소수로
    반환(예: -0.12 = 고점 대비 -12%). 달력 경계 리셋이 없다는 게 daily/weekly/
    monthly_return과의 핵심 차이다.
    """
    resolved_sorted = sorted(_resolved(entries), key=lambda e: e.date)
    cum = 0.0
    peak = 0.0
    drawdown = 0.0
    for e in resolved_sorted:
        cum += e.pnl_pct
        peak = max(peak, cum)
        drawdown = min(drawdown, cum - peak)
    return drawdown


def consecutive_losses(entries: list[PaperEntry]) -> int:
    """가장 최근 청산 거래부터 거슬러 올라가며 연속 손실 건수를 센다."""
    resolved_sorted = sorted(_resolved(entries), key=lambda e: e.date)
    count = 0
    for e in reversed(resolved_sorted):
        if e.pnl_pct <= 0:
            count += 1
        else:
            break
    return count
