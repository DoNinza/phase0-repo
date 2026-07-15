#!/usr/bin/env python3
"""워치리스트 일봉 로컬 캐시 수집 (2026-07-16, 대시보드 종목별 차트용).

대시보드가 매번 pykrx를 라이브 호출하지 않도록, KR 기본 후보군(20종목)+
ETF 기본 후보군(15종목) = 35종목의 일봉을 하루 한 번만 미리 받아
data/daily_bars/{ticker}.jsonl에 캐시한다. 증분 수집: 이미 캐시된
마지막 날짜 다음날부터만 받아온다(전체 재수집 안 함).

종목 단위로 실패를 격리한다(candidate_batch.run_batch와 동일 원칙) —
한 종목이 상장폐지·일시적 오류로 실패해도 나머지는 계속 진행.

사용법: python scripts/collect_daily_bars_watchlist.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from phase0.data.candidate_batch import DEFAULT_CANDIDATES as KR_DEFAULT
from phase0.data.daily_bar_store import append_bars, latest_date, store_path
from phase0.data.etf_candidates import DEFAULT_CANDIDATES as ETF_DEFAULT
from phase0.data.pykrx_ingest import fetch_ohlcv

WATCHLIST: list[str] = list(dict.fromkeys(KR_DEFAULT + ETF_DEFAULT))   # 중복 제거, 순서 유지

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT / "data" / "daily_bars"
HEARTBEAT_PATH = BASE_DIR / "heartbeat.txt"

LOOKBACK_DAYS_IF_EMPTY = 365 * 3   # 캐시가 비어있을 때 처음 받아올 과거 범위


def write_heartbeat() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def collect_ticker(ticker: str, end: str) -> tuple[int, str | None]:
    """(신규 수집 봉 개수, 오류메시지) 반환 — 오류가 나도 예외를 던지지 않는다."""
    path = store_path(BASE_DIR, ticker)
    last = latest_date(path)
    if last is None:
        start = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS_IF_EMPTY)).strftime("%Y%m%d")
    else:
        start = (dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)).strftime("%Y%m%d")

    if start > end:
        return 0, None   # 이미 최신 상태

    try:
        bars = fetch_ohlcv(ticker, start, end)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"

    append_bars(path, bars)
    return len(bars), None


def main() -> None:
    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")   # D-1까지만 — 룩어헤드 없음
    n_ok, n_new_bars, n_failed = 0, 0, 0
    for ticker in WATCHLIST:
        count, error = collect_ticker(ticker, end)
        if error:
            print(f"  {ticker}: 실패 ({error})")
            n_failed += 1
        else:
            print(f"  {ticker}: 신규 {count}봉")
            n_ok += 1
            n_new_bars += count

    print(f"\n워치리스트 {len(WATCHLIST)}종목 중 {n_ok}종목 성공(신규 {n_new_bars}봉), {n_failed}종목 실패")
    write_heartbeat()


if __name__ == "__main__":
    main()
