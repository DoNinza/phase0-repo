#!/usr/bin/env python3
"""KIS 분봉 이력 범위 실측 (STAGE 7 항목 5, 분봉 검증 Blocker).

.env에 채운 실제 KIS 인증정보로 토큰을 발급받고, 분봉조회 API를 호출해서
"과거 날짜 분봉이 실제로 나오는지"를 직접 확인한다. README에 기록해둔
"당일만 가능"이라는 잠정 결론(커뮤니티 자료 기반)을 사용자 본인 계좌로
검증하는 스크립트다.

이 스크립트는 인증정보를 절대 print/log하지 않는다 — access_token조차
앞 6자만 마스킹해서 보여준다.

사용법: python scripts/check_minute_bar_history.py [ticker]
"""

from __future__ import annotations

import sys

import requests

from phase0.config.kis_credentials import CredentialsMissingError, load_credentials

TR_ID_MINUTE_CHART = "FHKST03010200"  # 주식현재가 분봉조회


def issue_access_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={
            "grant_type": "client_credentials",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
        },
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    return token


def fetch_minute_chart(creds, token: str, ticker: str, hour: str = "153000") -> dict:
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
    return resp.json()


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "005930"

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    print(f"인증정보 로드됨: {creds!r}")  # __repr__이 마스킹 처리함

    print("액세스 토큰 발급 시도...")
    token = issue_access_token(creds)
    print(f"토큰 발급 성공 (마스킹: {token[:6]}...)")

    print(f"\n{ticker} 분봉조회 호출...")
    data = fetch_minute_chart(creds, token, ticker)

    rows = data.get("output2", [])
    print(f"응답 코드: {data.get('rt_cd')}, 메시지: {data.get('msg1')}")
    print(f"수신 봉 개수: {len(rows)}")

    dates = sorted({r.get("stck_bsop_date") or r.get("bsop_date") for r in rows if r})
    print(f"응답에 포함된 날짜 종류: {dates}")
    print(
        "\n판정: 응답에 오늘 날짜 하나만 있으면 '당일만 가능' 잠정 결론이 "
        "본인 계좌로도 확인된 것. 여러 날짜가 섞여 있으면 README의 잠정 결론을 "
        "수정해야 함."
    )


if __name__ == "__main__":
    main()
