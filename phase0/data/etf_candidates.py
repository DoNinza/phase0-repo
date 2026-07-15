"""국내 주식형 ETF 후보 종목 (2026-07-15, 개별주식 candidate_batch.py와 분리).

pykrx의 ETF 전용 함수(get_etf_ticker_name, get_etf_ohlcv_by_date 등)는
전체 시장 스냅샷에 의존해 개별주식과 동일한 상위 장애(KRX 서버 응답
변경, sharebook-kr/pykrx#190/191/193)를 그대로 물려받아 전부 깨져
있다 — 실측 확인(2026-07-15). 대신 일반 `get_market_ohlcv`(개별주식용
함수)가 ETF 종목코드에도 그대로 동작한다는 것을 확인해 이 목록을
검증했다: pykrx의 이름 대조가 아니라 실제 시세 데이터가 정상 반환되고
(코스피200 추종형 6종목의 최근 종가가 서로 근접해 같은 지수를
추종한다는 사실과 교차검증됨) 값이 그럴듯한지로 확인했다 — 개별주식
검증(실제 등록명 대조)보다 한 단계 약한 검증이라는 점을 정직하게
남긴다.

같은 이유(전체 ETF 목록 스냅샷 API 장애)로 이 목록도 "발행된 전체
국내 주식형 ETF"가 아니라 investing.com 등 공개 자료에서 확인한
손 고른 표본이다 — candidate_batch.DEFAULT_CANDIDATES와 동일한 한계.
"""

from __future__ import annotations

DEFAULT_CANDIDATES: list[str] = [
    "069500",  # KODEX 200
    "102110",  # TIGER 200
    "148020",  # KBSTAR 200
    "152100",  # ARIRANG 200
    "105190",  # KINDEX 200
    "069660",  # KOSEF 200
    "278530",  # KODEX 200TR
    "363580",  # KODEX 200 IT TR
    "091160",  # KODEX 반도체
    "091230",  # TIGER 반도체
    "091170",  # KODEX 은행
    "091180",  # KODEX 자동차
    "305720",  # KODEX 2차전지산업
    "229200",  # KODEX 코스닥150
    "244580",  # KODEX 바이오
]

# 확장 유니버스(2026-07-15) — 15종목으로는 신호 표본이 너무 작아(GDR
# 47~876건) VBP처럼 작은 표본에서 나온 양수 조합을 믿을 수 없는 상태였다.
# investing.com ETF 목록에서 국내 주식형·비레버리지·비인버스 섹터/스타일
# ETF를 추가로 찾아 동일 방법(get_market_ohlcv 실제 데이터 반환 확인)으로
# 검증했다.
EXPANDED_CANDIDATES: list[str] = DEFAULT_CANDIDATES + [
    "117700",  # KODEX 건설
    "117680",  # KODEX 철강
    "091220",  # TIGER 은행
    "102970",  # KODEX 증권
    "140700",  # KODEX 보험
    "266360",  # KODEX 미디어&엔터테인먼트
    "266420",  # KODEX 헬스케어
    "266410",  # KODEX 필수소비재
    "102960",  # KODEX 기계장비
    "140710",  # KODEX 운송
    "300950",  # KODEX 게임산업
    "226490",  # KODEX 코스피
    "237350",  # KODEX 코스피100
    "226980",  # KODEX 200 중소형
    "337140",  # KODEX 코스피 대형주
    "292190",  # KODEX KRX300
    "139220",  # TIGER 200 건설
    "139230",  # TIGER 200 중공업
    "139240",  # TIGER 200 철강소재
    "139250",  # TIGER 200 에너지화학
    "139260",  # TIGER 200 IT
    "139270",  # TIGER 200 금융
    "227540",  # TIGER 200 헬스케어
    "227550",  # TIGER 200 산업재
    "228790",  # TIGER 화장품
    "228800",  # TIGER 여행레저
    "228810",  # TIGER 미디어컨텐츠
    "315270",  # TIGER 200 커뮤니케이션서비스
]
