#!/usr/bin/env python3
"""실시간 KIS 호가창으로 슬리피지 가정 스팟체크 (costs.yaml slippage_buy/sell_normal).

배경: costs.yaml의 slippage_buy(0.05%)+slippage_sell_normal(0.10%) = 0.15%는
"초기 가정"(섀도우 테스트 후 확정) 태그가 붙어 있다. GDR이 유일하게 비용에
근접한(−0.16%) 가설이었으므로, 이 가정이 과대평가됐는지를 확인하는 게 새
가설을 더 만드는 것보다 저렴하고 근거가 확실한 다음 수다.

주의(정직한 한계): 이건 완전한 섀도우 테스트가 아니라 스팟체크다. 실제
섀도우 테스트(costs.yaml의 태그가 요구하는 것)는 여러 날에 걸쳐 실제 신호가
발생하는 순간의 호가창을 반복 관측해야 통계적으로 의미가 있다 — 이 스크립트는
"지금 이 순간" 유동성 상위 대형주의 최우선호가 스프레드가 대략 어느 자릿수인지
1회 확인하는 용도다. GDR 신호 발생 순간(장 시작 직후)의 스프레드는 장중과
다를 수 있다는 점도 한계로 남는다.

사용법: python scripts/check_orderbook_spread.py [ticker1,ticker2,...]
(기본값: candidate_batch.DEFAULT_CANDIDATES 중 유동성 상위 8종목)
"""

from __future__ import annotations

import sys

import requests

from phase0.config.costs import base_breakdown
from phase0.config.kis_credentials import CredentialsMissingError, load_credentials

TR_ID_ORDERBOOK = "FHKST01010200"  # 주식현재가 호가/예상체결

DEFAULT_SAMPLE = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "005380",  # 현대차
    "000270",  # 기아
    "035420",  # NAVER
    "105560",  # KB금융
    "051910",  # LG화학
    "032830",  # 삼성생명
]

ASSUMED_SLIPPAGE_ROUNDTRIP = 0.0005 + 0.0010   # costs.yaml slippage_buy + slippage_sell_normal


def issue_access_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_orderbook(creds, token: str, ticker: str) -> dict:
    resp = requests.get(
        f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": TR_ID_ORDERBOOK,
        },
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    tickers = sys.argv[1].split(",") if len(sys.argv) > 1 else DEFAULT_SAMPLE

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    print(f"인증정보 로드됨: {creds!r}")
    token = issue_access_token(creds)
    print(f"토큰 발급 성공 (마스킹: {token[:6]}...)\n")
    print(f"가정된 왕복 슬리피지(costs.yaml, 초기 가정): {ASSUMED_SLIPPAGE_ROUNDTRIP * 100:.4f}%\n")

    header = f"{'종목':>8}{'매수호가1':>12}{'매도호가1':>12}{'스프레드%':>11}"
    print(header)
    print("-" * len(header))

    spreads = []
    for ticker in tickers:
        data = fetch_orderbook(creds, token, ticker)
        out1 = data.get("output1", {})
        try:
            bid1 = float(out1["bidp1"])
            ask1 = float(out1["askp1"])
        except (KeyError, ValueError):
            print(f"{ticker:>8}  응답 필드 파싱 실패 — raw output1: {out1}")
            continue
        if bid1 <= 0 or ask1 <= 0:
            print(f"{ticker:>8}  호가 없음(장 마감/거래정지 등) — bid={bid1}, ask={ask1}")
            continue
        mid = (bid1 + ask1) / 2
        spread_pct = (ask1 - bid1) / mid
        spreads.append(spread_pct)
        print(f"{ticker:>8}{bid1:>12.0f}{ask1:>12.0f}{spread_pct * 100:>10.4f}%")

    if spreads:
        avg_spread = sum(spreads) / len(spreads)
        print(f"\n평균 최우선호가 스프레드: {avg_spread * 100:.4f}% (표본 {len(spreads)}종목, 지금 이 순간 1회 관측)")
        print(f"가정된 왕복 슬리피지: {ASSUMED_SLIPPAGE_ROUNDTRIP * 100:.4f}%")
        if avg_spread < ASSUMED_SLIPPAGE_ROUNDTRIP:
            print("→ 이 순간 스프레드는 가정보다 좁다 — 가정이 보수적(과대평가)일 가능성을 시사.")
        else:
            print("→ 이 순간 스프레드가 가정과 비슷하거나 넓다 — 가정이 과대평가라고 보기 어려움.")
        print(
            "\n주의: 이건 1회 스팟체크이지 통계적 섀도우 테스트가 아니다 — "
            "costs.yaml의 태그를 '확인된 사실'로 바꾸려면 여러 날·실제 신호 발생"
            "시점의 반복 관측이 필요하다(README 참고)."
        )


if __name__ == "__main__":
    main()
