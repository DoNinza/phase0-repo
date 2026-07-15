"""미국 주식 일봉 데이터 수집·클렌징 (2026-07-15, 한국주식 섹터와 분리).

pykrx_ingest.py와 같은 패턴(fetcher 주입으로 네트워크와 클렌징 로직 분리,
동일한 OhlcvBar 타입 산출)을 그대로 승계한다 — 그 덕분에 phase0.strategy.*,
phase0.backtest.g0_backtester, phase0.bootstrap.cluster_bootstrap,
phase0.ml.gdr_filter 등 시장에 무관하게 짜여진 코드는 전혀 수정 없이
미국주식 데이터에도 그대로 재사용된다.

데이터 소스: yfinance(무료, 조정종가 자동 반영 — auto_adjust=True로 분할·배당
조정된 O/H/L/C를 받아 인위적 갭을 방지). 알려진 한계: 이것도 "현재 대형주"를
과거에 소급 적용하는 손 고른 목록이라는 점에서 KOSPI 쪽과 동일한 생존편향이
있다 — 상장폐지·인수합병 종목을 포함한 진짜 시점 유니버스는 아니다.
"""

from __future__ import annotations

import warnings
from typing import Callable

import pandas as pd

from phase0.data.pykrx_ingest import OhlcvBar


def _to_yf_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _default_ohlcv_fetcher(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(
        ticker, start=_to_yf_date(start), end=_to_yf_date(end),
        progress=False, auto_adjust=True,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(ticker, axis=1, level=1)
    return df


def clean_ohlcv(raw: pd.DataFrame) -> list[OhlcvBar]:
    """yfinance 형식(Open/High/Low/Close/Volume, DatetimeIndex) DataFrame을 클렌징.

    pykrx_ingest.clean_ohlcv와 동일한 정합성 규칙(거래량 0 제외, 고가<저가나
    시가/종가가 범위를 벗어나는 행은 스킵+경고) — 자본 이벤트(분할 등)로 인한
    하루짜리 반올림 오차 때문에 종목 전체 이력을 버리는 것을 막기 위함이다.
    """
    bars: list[OhlcvBar] = []
    for idx, row in raw.iterrows():
        volume = int(row["Volume"])
        if volume == 0:
            continue
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        date = idx.strftime("%Y%m%d") if hasattr(idx, "strftime") else str(idx)
        if h < l:
            warnings.warn(f"{date}: high({h}) < low({l}) — 데이터 정합성 위반, 해당 일자 제외")
            continue
        if not (l <= o <= h):
            warnings.warn(f"{date}: open({o})이 low~high 범위[{l},{h}]를 벗어남, 해당 일자 제외")
            continue
        if not (l <= c <= h):
            warnings.warn(f"{date}: close({c})이 low~high 범위[{l},{h}]를 벗어남, 해당 일자 제외")
            continue
        bars.append(OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=volume))
    return bars


def fetch_ohlcv(
    ticker: str,
    start: str,
    end: str,
    fetcher: Callable[[str, str, str], pd.DataFrame] = _default_ohlcv_fetcher,
) -> list[OhlcvBar]:
    """개별 종목 일봉 수집 + 클렌징. start/end는 KR 섹터와 동일하게 YYYYMMDD 문자열.

    fetcher를 주입하면 네트워크 없이 테스트 가능(pykrx_ingest.fetch_ohlcv와 동일 패턴).
    """
    return clean_ohlcv(fetcher(ticker, start, end))
