#!/usr/bin/env python3
"""후보 종목 배치 수집을 실제 KRX 네트워크로 돌려보는 수동 스크립트.

pytest에는 포함하지 않는다 — 여러 종목에 대한 실제 네트워크 호출이라
시간이 걸리고 KRX 서버 상태에 좌우된다. 기본값은 DEFAULT_CANDIDATES
전체(플레이스홀더 목록, candidate_batch.py 주석 참고) 대신 앞쪽 일부만
돌려서 서버 부하와 실행 시간을 줄인다 — 전체 배치를 돌리려면 --all을 쓴다.

사용법:
  python scripts/run_candidate_batch.py [--all] [start] [end]
"""

import sys

from phase0.data.candidate_batch import DEFAULT_CANDIDATES, liquid_candidates, run_batch


def main() -> None:
    args = sys.argv[1:]
    run_all = "--all" in args
    args = [a for a in args if a != "--all"]

    start = args[0] if len(args) > 0 else "20260601"
    end = args[1] if len(args) > 1 else "20260714"
    tickers = DEFAULT_CANDIDATES if run_all else DEFAULT_CANDIDATES[:5]

    print(f"{len(tickers)}종목, {start}~{end} 배치 수집 시작 (전체 목록은 플레이스홀더 — README 참고)")
    results = run_batch(tickers, start, end, sleep_seconds=0.3)

    print(f"\n{'종목':<8}{'봉수':>6}{'시작':>10}{'끝':>10}{'평균일거래대금(추정)':>20}")
    for r in results:
        if r.ok:
            print(f"{r.ticker:<8}{r.n_days:>6}{r.start_date:>10}{r.end_date:>10}{r.avg_daily_value_krw:>20,.0f}")
        else:
            print(f"{r.ticker:<8}{'실패':>6}  {r.error}")

    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n성공 {len(ok)} / 실패 {len(failed)}")

    liquid = liquid_candidates(results, min_avg_value_krw=1_000_000_000)  # 10억원/일 예시 기준
    print(f"유동성 기준(평균 일 거래대금 추정 ≥ 10억) 통과: {liquid}")


if __name__ == "__main__":
    main()
