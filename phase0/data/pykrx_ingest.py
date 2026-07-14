"""KRX 일봉 데이터 수집·클렌징 (기획안 STAGE 7 항목 6·7, R-09 데이터 공급자 정책).

pykrx로 실제 KRX 데이터를 가져오되, 클렌징 로직은 네트워크 호출과 분리해
fetcher를 주입받는 구조로 만든다 — 네트워크 없이도 pytest로 검증 가능해야
한다는 이 저장소의 기존 원칙(costs.py의 costs.yaml 주입, g0_backtester의
DailyBar/Signal 주입)과 동일한 패턴이다.

알려진 제약 (2026-07-14 확인): pykrx의 전체 시장 스냅샷 계열 함수
(get_market_ticker_list, get_market_cap 등)가 KRX 서버 응답 형식 변경으로
"Expecting value: line 1 column 1" 오류를 내며 깨져 있다 — pykrx 저장소에
동일 증상의 미해결 이슈가 다수 존재한다(sharebook-kr/pykrx#190, #191, #193).
개별 종목 시계열(get_market_ohlcv)은 정상 동작한다. 따라서 상장폐지 종목을
포함한 과거 시점 유니버스 구성(생존편향 방지, 항목 7)은 이 상위 장애가
풀리기 전까지 이 모듈만으로 완결할 수 없다 — fetch_universe()는 그 사실을
조용히 삼키지 않고 명확한 예외로 알리는 자리다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import pandas as pd


@dataclass
class OhlcvBar:
    """클렌징을 마친 개별 종목 일봉. volume은 유동성 필터(§거래대금 기준)용."""
    date: str        # YYYYMMDD
    open: float
    high: float
    low: float
    close: float
    volume: int


class UniverseUnavailableError(RuntimeError):
    """전체 시장 스냅샷 API(티커 목록 등)를 가져올 수 없을 때 발생.

    현재(2026-07-14) 알려진 원인은 KRX 서버 응답 변경에 따른 pykrx 자체 장애이며,
    이 프로젝트 코드의 결함이 아니다. 종목을 이미 알고 있다면 fetch_ohlcv()로
    개별 수집은 가능하다.
    """


def _default_ohlcv_fetcher(ticker: str, start: str, end: str) -> pd.DataFrame:
    from pykrx import stock
    return stock.get_market_ohlcv(start, end, ticker)


def clean_ohlcv(raw: pd.DataFrame) -> list[OhlcvBar]:
    """pykrx get_market_ohlcv 형식(시가/고가/저가/종가/거래량) DataFrame을 클렌징.

    - 거래량 0인 행(휴장일이 날짜 인덱스에 섞여 들어온 경우) 제외 — 무거래일은
      phase0.engine.core.exposure()의 0 기여로 이미 반영되므로 여기서 중복 처리 안 함.
    - 고가<저가, 시가/종가가 [저가,고가] 범위를 벗어나는 등 정합성 위반 행은
      조용히 넘기지 않고 ValueError로 기각 — 잘못된 봉으로 G0 판정이 오염되는
      것을 데이터 입구에서 막는다.
    """
    bars: list[OhlcvBar] = []
    for idx, row in raw.iterrows():
        volume = int(row["거래량"])
        if volume == 0:
            continue
        o, h, l, c = float(row["시가"]), float(row["고가"]), float(row["저가"]), float(row["종가"])
        date = idx.strftime("%Y%m%d") if hasattr(idx, "strftime") else str(idx)
        if h < l:
            raise ValueError(f"{date}: 고가({h}) < 저가({l}) — 데이터 정합성 위반")
        if not (l <= o <= h):
            raise ValueError(f"{date}: 시가({o})가 저가~고가 범위[{l},{h}]를 벗어남")
        if not (l <= c <= h):
            raise ValueError(f"{date}: 종가({c})가 저가~고가 범위[{l},{h}]를 벗어남")
        bars.append(OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=volume))
    return bars


def fetch_ohlcv(
    ticker: str,
    start: str,
    end: str,
    fetcher: Callable[[str, str, str], pd.DataFrame] = _default_ohlcv_fetcher,
) -> list[OhlcvBar]:
    """개별 종목 일봉 수집 + 클렌징. fetcher를 주입하면 네트워크 없이 테스트 가능."""
    return clean_ohlcv(fetcher(ticker, start, end))


def to_daily_bar(bar: OhlcvBar):
    """phase0.backtest.g0_backtester.DailyBar로 변환 (volume 등 부가정보는 버림)."""
    from phase0.backtest.g0_backtester import DailyBar
    return DailyBar(date=bar.date, open=bar.open, high=bar.high, low=bar.low, close=bar.close)


def _default_universe_fetcher(date: str, market: str) -> list[str]:
    from pykrx import stock
    return list(stock.get_market_ticker_list(date, market=market))


def fetch_universe(
    date: str,
    market: str = "KOSPI",
    fetcher: Callable[[str, str], Sequence[str]] = _default_universe_fetcher,
) -> list[str]:
    """전체 시장 티커 목록 조회. 상위 스냅샷 API 장애 시 UniverseUnavailableError로 변환."""
    try:
        tickers = list(fetcher(date, market))
    except Exception as exc:
        raise UniverseUnavailableError(
            f"{date} {market} 유니버스 조회 실패: {exc!r} — pykrx 전체 시장 스냅샷 API가 "
            "KRX 서버 응답 변경으로 깨져 있는 것으로 보임(2026-07-14 확인, "
            "sharebook-kr/pykrx#190/191/193 참고, 공식 수정 미배포). 종목별 "
            "get_market_ohlcv는 정상 동작하므로 티커를 이미 아는 경우 fetch_ohlcv()로 "
            "개별 수집은 가능하다."
        ) from exc
    if not tickers:
        raise UniverseUnavailableError(
            f"{date} {market} 티커 목록이 비어 있음 — pykrx 전체 시장 스냅샷 API 장애 의심 "
            "(sharebook-kr/pykrx#190/191/193 참고)"
        )
    return tickers
