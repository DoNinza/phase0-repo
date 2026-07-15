#!/usr/bin/env python3
"""오늘의 분봉을 수집·축적 (STAGE 7 항목 4 재개, 2026-07-15).

배경: KIS 분봉 API는 과거 이력을 안 주므로(README, 분봉 검증 Blocker),
매일 자동으로 "오늘" 분봉을 저장해나가는 것만이 우리만의 분봉 데이터셋을
만드는 유일한 길이다. 실측(2026-07-15, 삼성전자)으로 확인된 한계: 1회
호출은 FID_INPUT_HOUR_1까지의 최근 30개 봉만 준다 — 그래서 장 마감
(15:30)부터 30분씩 시각을 당겨가며 여러 번 호출해 하루 전체(09:00~15:30)를
모은다. 장 시작 전에는 데이터가 없어 그 구간 호출은 빈 응답이 정상이다.

실주문과 무관한 순수 시세 조회(읽기 전용)만 사용한다.

사용법: python scripts/collect_minute_bars.py [--tickers T1,T2,...]
(기본값: candidate_batch.DEFAULT_CANDIDATES 20종목 — API 호출량을 낮게
유지하기 위해 확장 유니버스가 아니라 기본 유니버스로 시작한다.)
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import requests

from phase0.config.kis_credentials import CredentialsMissingError, load_credentials
from phase0.data.candidate_batch import DEFAULT_CANDIDATES
from phase0.data.minute_bar_store import MinuteBar, append_bars, existing_dates, store_path

TR_ID_MINUTE_CHART = "FHKST03010200"  # 주식현재가 분봉조회

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "data" / "minute_bars"
HEARTBEAT_PATH = STORE_DIR / "heartbeat.txt"

MARKET_CLOSE_HOUR = "153000"
MARKET_OPEN_HOUR = "090000"
WINDOW_MINUTES = 30   # 실측 확인된 1회 호출당 반환 개수


def write_heartbeat() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def issue_access_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_minute_chart(creds, token: str, ticker: str, hour: str) -> list[dict]:
    resp = requests.get(
        f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": TR_ID_MINUTE_CHART,
        },
        params={
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_HOUR_1": hour,
            "FID_PW_DATA_INCU_YN": "Y",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("output2", [])


def _hour_sequence() -> list[str]:
    """장마감(15:30)부터 장시작(09:00)까지 30분 간격으로 당겨가는 시각 목록."""
    hours = []
    t = dt.datetime.strptime(MARKET_CLOSE_HOUR, "%H%M%S")
    open_t = dt.datetime.strptime(MARKET_OPEN_HOUR, "%H%M%S")
    while t >= open_t:
        hours.append(t.strftime("%H%M%S"))
        t -= dt.timedelta(minutes=WINDOW_MINUTES)
    return hours


def collect_ticker(creds, token: str, ticker: str) -> int:
    rows_all: list[dict] = []
    for hour in _hour_sequence():
        rows = fetch_minute_chart(creds, token, ticker, hour)
        rows_all.extend(rows)
        time.sleep(0.15)   # KIS 실전 호출 한도(초당 약 20건) 여유를 두고 준수

    bars = []
    for r in rows_all:
        try:
            bars.append(MinuteBar(
                date=r["stck_bsop_date"], time=r["stck_cntg_hour"],
                open=float(r["stck_oprc"]), high=float(r["stck_hgpr"]),
                low=float(r["stck_lwpr"]), close=float(r["stck_prpr"]),
                volume=int(r["cntg_vol"]),
            ))
        except (KeyError, ValueError):
            continue   # 예상 밖 필드 — 그 행만 건너뜀, 나머지는 살림

    append_bars(store_path(STORE_DIR, ticker), bars)
    return len(bars)


def main() -> None:
    args = sys.argv[1:]
    tickers = DEFAULT_CANDIDATES
    for i, a in enumerate(args):
        if a == "--tickers":
            tickers = args[i + 1].split(",")

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    today = dt.date.today().strftime("%Y%m%d")
    token = issue_access_token(creds)

    print(f"분봉 수집: {len(tickers)}종목, {today}, 시각 {len(_hour_sequence())}구간(30분씩)\n")

    for ticker in tickers:
        path = store_path(STORE_DIR, ticker)
        if today in existing_dates(path):
            print(f"  {ticker}: 오늘 이미 수집됨 — 건너뜀")
            continue
        try:
            n = collect_ticker(creds, token, ticker)
        except Exception as exc:
            print(f"  {ticker}: 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        print(f"  {ticker}: {n}봉 수집 (저장: {path.name})")

    write_heartbeat()


if __name__ == "__main__":
    main()
