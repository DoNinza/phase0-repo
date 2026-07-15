#!/usr/bin/env python3
"""키움 REST API로 한국주식 분봉 대량 백필 (2026-07-15).

KIS 분봉(오늘 것만, 호출당 30개)과 결정적으로 다른 점: 키움 `ka10080`
("주식분봉차트조회요청")은 `cont-yn`/`next-key` 헤더로 연속조회가 되고,
호출당 900개(5분봉)를 준다. 실측(2026-07-15, 삼성전자): 5회 호출만으로
2026-04-20까지(약 3개월) 도달했고 그 시점에도 `cont-yn`은 여전히 "Y"였다
— 그래서 이 스크립트는 `cont-yn`이 끊길 때까지(또는 안전 상한까지)
페이지네이션해서 한 번에 몇 달치를 백필한다.

phase0.data.minute_bar_store(MinuteBar/append_bars/store_path)를 KIS
분봉 축적과 그대로 재사용 — 저장 형식은 소스 무관 공통. append_bars가
(날짜,시각) 기준 중복을 걸러내므로 재실행해도 안전(멱등).

주의(정직한 한계): 가격 필드(cur_prc/open_pric/high_pric/low_pric)에
전일대비 부호(+/-)가 접두사로 붙어 있다 — 실제 가격은 항상 양수이므로
부호는 버리고 절대값만 취한다. 이 종목·이 기간에서 실측된 값이며,
Kiwoom REST API의 초당 호출 한도는 공식 확인이 안 돼 있어 보수적으로
0.3초 간격을 둔다.

사용법: python scripts/collect_minute_bars_kiwoom.py [--universe default|expanded]
                                                       [--tickers T1,T2,...] [--max-calls N]
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

import requests

from phase0.config.kiwoom_credentials import CredentialsMissingError, load_credentials
from phase0.data.candidate_batch import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.minute_bar_store import MinuteBar, append_bars, store_path

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "data" / "minute_bars_kiwoom"
HEARTBEAT_PATH = STORE_DIR / "heartbeat.txt"

TR_ID = "ka10080"
TIC_SCOPE = "5"              # 5분봉
MAX_CALLS_PER_TICKER = 60    # 안전 상한(무한루프 방지) — 60회x900개 ≈ 5.4만봉
SLEEP_SECONDS = 0.3          # 초당 호출 한도 미확인 — 보수적으로 여유를 둠


def write_heartbeat() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def issue_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/token",
        headers={"Content-Type": "application/json;charset=UTF-8"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "secretkey": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("return_code") != 0:
        raise RuntimeError(f"토큰 발급 실패: {data.get('return_msg')}")
    return data["token"]


def strip_sign(value: str) -> float:
    """가격 필드의 전일대비 부호(+/-) 접두사를 버리고 절대값만 취한다."""
    return float(value.lstrip("+-")) if value else 0.0


def fetch_ticker_bars(creds, token: str, ticker: str, max_calls: int) -> list[MinuteBar]:
    headers_base = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": TR_ID,
    }
    body = {"stk_cd": ticker, "tic_scope": TIC_SCOPE, "upd_stkpc_tp": "1"}

    bars: list[MinuteBar] = []
    cont_yn, next_key = "N", ""
    for _ in range(max_calls):
        headers = dict(headers_base, **{"cont-yn": cont_yn, "next-key": next_key})
        resp = requests.post(f"{creds.base_url}/api/dostk/chart", headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("return_code") != 0:
            break

        for r in data.get("stk_min_pole_chart_qry", []):
            cntr_tm = r.get("cntr_tm", "")
            if len(cntr_tm) != 14:
                continue
            try:
                bars.append(MinuteBar(
                    date=cntr_tm[:8], time=cntr_tm[8:],
                    open=strip_sign(r["open_pric"]), high=strip_sign(r["high_pric"]),
                    low=strip_sign(r["low_pric"]), close=strip_sign(r["cur_prc"]),
                    volume=int(r["trde_qty"]),
                ))
            except (KeyError, ValueError):
                continue

        cont_yn = resp.headers.get("cont-yn", "N")
        next_key = resp.headers.get("next-key", "")
        if cont_yn != "Y" or not next_key:
            break
        time.sleep(SLEEP_SECONDS)

    return bars


def main() -> None:
    args = sys.argv[1:]
    universe = "default"
    tickers = None
    max_calls = MAX_CALLS_PER_TICKER
    for i, a in enumerate(args):
        if a == "--tickers":
            tickers = args[i + 1].split(",")
        if a == "--universe":
            universe = args[i + 1]
        if a == "--max-calls":
            max_calls = int(args[i + 1])

    if tickers is None:
        tickers = UNIVERSES[universe]

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    token = issue_token(creds)
    print(f"키움 분봉 백필: {len(tickers)}종목, 종목당 최대 {max_calls}회 호출({TIC_SCOPE}분봉)\n")

    for ticker in tickers:
        try:
            bars = fetch_ticker_bars(creds, token, ticker, max_calls)
        except Exception as exc:
            print(f"  {ticker}: 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        path = store_path(STORE_DIR, ticker)
        append_bars(path, bars)
        dates = sorted({b.date for b in bars})
        span = f"{dates[0]}~{dates[-1]}" if dates else "(없음)"
        print(f"  {ticker}: {len(bars)}봉 확인 (기간 {span})")
        time.sleep(SLEEP_SECONDS)

    write_heartbeat()


if __name__ == "__main__":
    main()
