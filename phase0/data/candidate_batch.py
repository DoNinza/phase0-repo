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

# 확장 유니버스(STAGE 7 항목 9·10 표본 확대, 2026-07-15). AlgoLab 블로그
# 리서치 이후 네 전략(VCB-Gap/GDR/GDR-V/VBP) 전부가 insufficient_sample로
# 막혀 있어, 새 조건을 더 얹기보다 표본 크기를 늘리는 쪽이 우선순위가
# 높다고 판단해 추가했다. companiesmarketcap.com에서 시가총액 상위
# 100위 내 KOSPI 종목을 조사한 뒤(2026-07-15), 종목코드 하나하나를
# pykrx.stock.get_market_ticker_name()으로 실제 등록명과 대조 검증해
# 오류를 걸러냈다 — 코스닥(.KQ) 종목·우선주·ADR 전용 코드는 제외.
# 이것도 여전히 "시가총액 상위" 편향(생존편향의 한 형태)이 있는 손 고른
# 목록이라는 점은 DEFAULT_CANDIDATES와 동일하다 — 항목 7(전체 유니버스,
# 상장폐지 포함)의 완전한 해소는 아니다.
EXPANDED_CANDIDATES: list[str] = DEFAULT_CANDIDATES + [
    "402340",  # SK스퀘어
    "329180",  # HD현대중공업
    "034020",  # 두산에너빌리티
    "012450",  # 한화에어로스페이스
    "009150",  # 삼성전기
    "034730",  # SK
    "267260",  # HD현대일렉트릭
    "010120",  # LS ELECTRIC
    "000810",  # 삼성화재
    "298040",  # 효성중공업
    "042660",  # 한화오션
    "009540",  # HD한국조선해양
    "316140",  # 우리금융지주
    "000150",  # 두산
    "010130",  # 고려아연
    "042700",  # 한미반도체
    "138040",  # 메리츠금융지주
    "011200",  # HMM
    "010140",  # 삼성중공업
    "064350",  # 현대로템
    "017670",  # SK텔레콤
    "033780",  # KT&G
    "024110",  # 기업은행
    "010950",  # S-Oil
    "011070",  # LG이노텍
    "018260",  # 삼성에스디에스
    "003550",  # LG
    "079550",  # LIG디펜스앤에어로스페이스
    "278470",  # 에이피알
    "047810",  # 한국항공우주
    "086280",  # 현대글로비스
    "267250",  # HD현대
    "003670",  # 포스코퓨처엠
    "071050",  # 한국금융지주
    "030200",  # KT
    "272210",  # 한화시스템
    "307950",  # 현대오토에버
    "005940",  # NH투자증권
    "000720",  # 현대건설
    "323410",  # 카카오뱅크
    "259960",  # 크래프톤
    "096770",  # SK이노베이션
    "005830",  # DB손해보험
    "016360",  # 삼성증권
    "352820",  # 하이브
    "047050",  # 포스코인터내셔널
    "443060",  # HD현대마린솔루션
    "161390",  # 한국타이어앤테크놀로지
    "090430",  # 아모레퍼시픽
    "006260",  # LS
    "003490",  # 대한항공
    "039490",  # 키움증권
    "003230",  # 삼양식품
    "028050",  # 삼성E&A
    "000880",  # 한화
    "006800",  # 미래에셋증권
    "180640",  # 한진칼
    "078930",  # GS
    "007660",  # 이수페타시스
    "021240",  # 코웨이
    "047040",  # 대우건설
    "064400",  # LG씨엔에스
    "241560",  # 두산밥캣
    "032640",  # LG유플러스
    "353200",  # 대덕전자
    "326030",  # SK바이오팜
    "009830",  # 한화솔루션
    "034220",  # LG디스플레이
    "001440",  # 대한전선
    "062040",  # 산일전기
    "377300",  # 카카오페이
    "029780",  # 삼성카드
    "271560",  # 오리온
    "000100",  # 유한양행
    "004170",  # 신세계
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
