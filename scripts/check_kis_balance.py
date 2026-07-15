#!/usr/bin/env python3
"""KIS 실계좌 잔고 조회 (읽기 전용, 주문 없음) — 2026-07-16.

지금까지의 GDR/ETF-GDR 페이퍼 트레이딩은 전부 자체 로그(JSONL)로만
손익을 시뮬레이션했다 — 실제 KIS 계좌에는 어떤 주문도 낸 적이 없다.
이 스크립트는 그 사실과 별개로, API 인증정보가 가리키는 실제 계좌의
현재 잔고(예수금·보유종목·평가손익)를 읽기 전용으로 조회한다.

TR: 주식잔고조회 (실전 TTTC8434R / 모의 VTTC8434R) — KIS_ENV에 따라 자동 선택.
"""

from __future__ import annotations

import requests

from phase0.config.kis_credentials import CredentialsMissingError, load_credentials

TR_ID = {"prod": "TTTC8434R", "vps": "VTTC8434R"}


def issue_access_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_balance(creds, token: str) -> dict:
    resp = requests.get(
        f"{creds.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": TR_ID[creds.env],
            "custtype": "P",
        },
        params={
            "CANO": creds.account_no,
            "ACNT_PRDT_CD": creds.account_product_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    print(f"조회 환경: {creds.env} ({'실전' if creds.env == 'prod' else '모의투자'})")
    token = issue_access_token(creds)
    data = fetch_balance(creds, token)

    if data.get("rt_cd") != "0":
        print(f"조회 실패: rt_cd={data.get('rt_cd')} msg={data.get('msg1')}")
        return

    holdings = [h for h in data.get("output1", []) if int(h.get("hldg_qty", "0")) > 0]
    summary = (data.get("output2") or [{}])[0]

    print(f"\n예수금총금액: {int(summary.get('dnca_tot_amt', 0)):,}원")
    print(f"총평가금액(주식+예수금): {int(summary.get('tot_evlu_amt', 0)):,}원")
    print(f"총평가손익금액: {int(summary.get('evlu_pfls_smtl_amt', 0)):,}원")
    print(f"보유종목 수: {len(holdings)}건\n")

    if holdings:
        print(f"{'종목코드':<10}{'종목명':<16}{'수량':>10}{'평가손익률':>12}")
        print("-" * 50)
        for h in holdings:
            print(f"{h.get('pdno',''):<10}{h.get('prdt_name',''):<16}"
                  f"{int(h.get('hldg_qty', 0)):>10,}{float(h.get('evlu_pfls_rt', 0)):>11.2f}%")


if __name__ == "__main__":
    main()
