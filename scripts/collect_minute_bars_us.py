#!/usr/bin/env python3
"""미국주식 5분봉 백필 + 축적 (2026-07-15).

KIS 분봉(KR 섹터)과 결정적으로 다른 점: yfinance는 5분봉을 **최근 60일치를
한 번에** 준다 — 그래서 한국처럼 "오늘 것만 매일 조금씩 쌓기"가 아니라
지금 당장 60일 백필이 가능하다(1분봉은 yfinance가 최근 7~8일만 주므로
이번 버전에서는 쓰지 않는다).

다만 yfinance 자체가 60일보다 오래된 인트라데이 데이터를 보관하지
않으므로, 롤링 윈도우가 지나가기 전에 이 스크립트를 주기적으로
재실행해 우리 저장소에 눌러 담아야 과거분이 유실되지 않는다 — 재실행은
멱등(이미 있는 (날짜,시각) 봉은 phase0.data.minute_bar_store.append_bars가
자동으로 걸러낸다).

phase0.data.minute_bar_store의 MinuteBar/append_bars/store_path를 KR
분봉 축적과 그대로 재사용한다 — 저장 형식은 시장 무관 공통.

사용법: python scripts/collect_minute_bars_us.py [--tickers T1,T2,...]
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

from phase0.data.minute_bar_store import MinuteBar, append_bars, store_path
from phase0.data.us_candidates import DEFAULT_CANDIDATES

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "data" / "minute_bars_us"
HEARTBEAT_PATH = STORE_DIR / "heartbeat.txt"

INTERVAL = "5m"
PERIOD = "60d"


def write_heartbeat() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def fetch_5m(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(ticker, period=PERIOD, interval=INTERVAL, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, axis=1, level=1)
    return df


def to_bars(df: pd.DataFrame) -> list[MinuteBar]:
    bars = []
    for idx, row in df.iterrows():
        try:
            bars.append(MinuteBar(
                date=idx.strftime("%Y%m%d"), time=idx.strftime("%H%M%S"),
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=int(row["Volume"]),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def main() -> None:
    args = sys.argv[1:]
    tickers = DEFAULT_CANDIDATES
    for i, a in enumerate(args):
        if a == "--tickers":
            tickers = args[i + 1].split(",")

    print(f"미국주식 {INTERVAL}봉 수집: {len(tickers)}종목, 최근 {PERIOD}\n")

    for ticker in tickers:
        try:
            df = fetch_5m(ticker)
        except Exception as exc:
            print(f"  {ticker}: 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        bars = to_bars(df)
        path = store_path(STORE_DIR, ticker)
        append_bars(path, bars)
        print(f"  {ticker}: 응답 {len(bars)}봉 확인 (신규분만 실제 저장, 기존 중복은 자동 제외)")

    write_heartbeat()


if __name__ == "__main__":
    main()
