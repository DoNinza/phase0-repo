#!/usr/bin/env python3
"""실제 KRX 네트워크 호출로 phase0.data.pykrx_ingest 동작을 확인하는 수동 스크립트.

pytest에는 포함하지 않는다 — 네트워크 상태·KRX 서버 가용성에 좌우되는 비결정적
호출이기 때문이다(print_tables.py와 같은 위치의 "사람이 직접 돌려보는" 스크립트).

사용법: python scripts/ingest_real_sample.py [ticker] [start] [end]
"""

import sys

from phase0.data.pykrx_ingest import UniverseUnavailableError, fetch_ohlcv, fetch_universe


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"
    start = sys.argv[2] if len(sys.argv) > 2 else "20260701"
    end = sys.argv[3] if len(sys.argv) > 3 else "20260714"

    print(f"[개별 종목] {ticker} {start}~{end} 일봉 수집 시도...")
    bars = fetch_ohlcv(ticker, start, end)
    print(f"  -> {len(bars)}봉 수집 성공 (클렌징 후)")
    for b in bars[:3]:
        print(f"     {b}")

    print(f"\n[전체 유니버스] {end} KOSPI 티커 목록 조회 시도...")
    try:
        tickers = fetch_universe(end, market="KOSPI")
        print(f"  -> {len(tickers)}종목 조회 성공")
    except UniverseUnavailableError as exc:
        print(f"  -> 실패(현재 알려진 상위 장애): {exc}")


if __name__ == "__main__":
    main()
