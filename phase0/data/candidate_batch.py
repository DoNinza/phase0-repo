"""후보 종목 배치 수집·유동성 요약 (기획안 STAGE 7 항목 4, v3 T-03 승계).

phase0.data.pykrx_ingest.fetch_ohlcv가 실제로 동작하는 것을 확인했으므로,
그 위에 "후보 리스트 -> 종목별 일봉 수집 -> 유동성 요약" 배치를 얹는다.
개별 종목 fetch 실패(상장폐지, 일시적 네트워크 오류 등)가 배치 전체를
죽이지 않도록 종목 단위로 격리한다.

주의(중요): DEFAULT_CANDIDATES는 STAGE 7 항목 7(pykrx 전체 시장 스냅샷
장애)이 막혀 있는 상태에서 임시로 손으로 고른 대형·고유동성 KOSPI 종목
예시 목록이다. 실시간 조회로 검증된 "상장폐지 포함 과거 유니버스"가 아니며,
실전 후보 선정에는 부적합하다 — 배치 파이프라인 자체를 실제 데이터로
검증하기 위한 플레이스홀더일 뿐이다. 실제 후보 50종목은 항목 7이 풀리거나
대체 소스(KRX 정보데이터시스템 등)를 구한 뒤 사용자가 직접 확정해야 한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

from phase0.data.pykrx_ingest import OhlcvBar, fetch_ohlcv

# 손으로 고른 대형·고유동성 KOSPI 종목 예시(플레이스홀더, 위 주의사항 참고).
# 실행 전 실제 후보 리스트로 교체할 것.
DEFAULT_CANDIDATES: list[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "373220",  # LG에너지솔루션
    "207940",  # 삼성바이오로직스
    "005380",  # 현대차
    "000270",  # 기아
    "068270",  # 셀트리온
    "005490",  # POSCO홀딩스
    "105560",  # KB금융
    "055550",  # 신한지주
    "035420",  # NAVER
    "035720",  # 카카오
    "012330",  # 현대모비스
    "028260",  # 삼성물산
    "066570",  # LG전자
    "051910",  # LG화학
    "006400",  # 삼성SDI
    "015760",  # 한국전력
    "032830",  # 삼성생명
    "086790",  # 하나금융지주
]


@dataclass
class TickerSummary:
    ticker: str
    n_days: int
    start_date: str | None
    end_date: str | None
    avg_daily_value_krw: float | None   # proxy: mean(close * volume) — 실제 거래대금 아님
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def summarize_bars(ticker: str, bars: Sequence[OhlcvBar]) -> TickerSummary:
    """일봉 리스트에서 유동성 요약 계산. 네트워크와 분리되어 있어 단위테스트 가능."""
    if not bars:
        return TickerSummary(ticker=ticker, n_days=0, start_date=None, end_date=None,
                              avg_daily_value_krw=None, error="수집된 봉이 없음")
    values = [b.close * b.volume for b in bars]
    return TickerSummary(
        ticker=ticker,
        n_days=len(bars),
        start_date=bars[0].date,
        end_date=bars[-1].date,
        avg_daily_value_krw=sum(values) / len(values),
    )


def run_batch(
    tickers: Sequence[str],
    start: str,
    end: str,
    fetch: Callable[[str, str, str], list[OhlcvBar]] = fetch_ohlcv,
    sleep_seconds: float = 0.0,
) -> list[TickerSummary]:
    """종목별로 격리된 배치 수집. 한 종목이 실패해도 나머지는 계속 진행한다.

    sleep_seconds: 실제 KRX 호출 시 서버 부하를 줄이기 위한 요청 간 대기(초).
    테스트에서는 0으로 둔다.
    """
    results: list[TickerSummary] = []
    for i, ticker in enumerate(tickers):
        if i > 0 and sleep_seconds > 0:
            time.sleep(sleep_seconds)
        try:
            bars = fetch(ticker, start, end)
            results.append(summarize_bars(ticker, bars))
        except Exception as exc:
            results.append(TickerSummary(ticker=ticker, n_days=0, start_date=None,
                                          end_date=None, avg_daily_value_krw=None,
                                          error=f"{type(exc).__name__}: {exc}"))
    return results


def liquid_candidates(summaries: Sequence[TickerSummary], min_avg_value_krw: float) -> list[str]:
    """유동성 기준(평균 일 거래대금 프록시)을 통과한 종목만 필터링."""
    return [
        s.ticker for s in summaries
        if s.ok and s.avg_daily_value_krw is not None and s.avg_daily_value_krw >= min_avg_value_krw
    ]
