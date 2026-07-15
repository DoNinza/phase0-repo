"""일봉 -> 주봉/월봉 리샘플링 (2026-07-16, 대시보드 종목별 차트용).

순수 함수 — 네트워크·파일 I/O 없이 OhlcvBar 리스트만 다뤄 pytest로
검증 가능하다(daily_bar_store.py의 캐시 I/O와 분리된 이유와 동일한
원칙, costs.py의 주입 패턴 참고).
"""

from __future__ import annotations

import datetime as dt
from typing import Callable, Sequence

from phase0.data.pykrx_ingest import OhlcvBar


def _week_key(date: str) -> str:
    d = dt.datetime.strptime(date, "%Y%m%d").date()
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _month_key(date: str) -> str:
    return date[:6]   # YYYYMM


def _resample(bars: Sequence[OhlcvBar], key_fn: Callable[[str], str]) -> list[OhlcvBar]:
    if not bars:
        return []
    ordered = sorted(bars, key=lambda b: b.date)
    groups: dict[str, list[OhlcvBar]] = {}
    for b in ordered:
        groups.setdefault(key_fn(b.date), []).append(b)

    result = []
    for key in sorted(groups.keys()):
        group = groups[key]
        result.append(OhlcvBar(
            date=group[-1].date,   # 구간의 마지막 거래일을 대표 날짜로
            open=group[0].open,
            high=max(b.high for b in group),
            low=min(b.low for b in group),
            close=group[-1].close,
            volume=sum(b.volume for b in group),
        ))
    return result


def resample_weekly(daily_bars: Sequence[OhlcvBar]) -> list[OhlcvBar]:
    return _resample(daily_bars, _week_key)


def resample_monthly(daily_bars: Sequence[OhlcvBar]) -> list[OhlcvBar]:
    return _resample(daily_bars, _month_key)
