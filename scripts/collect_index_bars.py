#!/usr/bin/env python3
"""지수(코스피/코스닥/코스피200) 일봉 로컬 캐시 수집 (2026-07-16, 대시보드 "B1: 지수
스트립"용).

pykrx의 get_index_ohlcv()는 KRX 서버 응답 형식 문제로 깨져 있다(README의
"pykrx 전체 시장 스냅샷 계열 함수 장애" 항목과 동일 증상, 개별 지수 계열도
확인 결과 "Expecting value: line 1 column 1" 오류) — 그래서 collect_daily_
bars_watchlist.py(개별 종목, pykrx)와 달리 이 스크립트는 KIS Open API의
일자별지수시세(inquire-daily-indexchartprice) 엔드포인트로 지수 일봉을
받는다. 저장 형식은 동일한 OhlcvBar/JSONL 캐시(phase0/data/daily_bar_store.py)
를 그대로 재사용한다 — 지수 OHLCV도 종목 일봉과 모양이 같기 때문에 새
저장 모듈을 만들지 않는다.

증분 수집: 이미 캐시된 마지막 날짜 다음날부터 D-1까지만 받는다(당일 봉은
아직 형성 중이라 시가=고가=저가=종가로 나오는 것을 실측 확인 — 룩어헤드
방지 원칙, collect_daily_bars_watchlist.py와 동일).

지수 단위로 실패를 격리한다(candidate_batch.run_batch와 동일 원칙) — 코스피
조회가 실패해도 코스닥/코스피200은 계속 진행.

사용법: python scripts/collect_index_bars.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import requests

from phase0.config.kis_credentials import CredentialsMissingError, KisCredentials, load_credentials
from phase0.data.daily_bar_store import append_bars, latest_date, store_path
from phase0.data.pykrx_ingest import OhlcvBar

# FID_INPUT_ISCD 코드 — generate_dashboard.py가 이 키("kospi"/"kosdaq"/
# "kospi200")를 그대로 읽으므로 이름을 바꿀 경우 그쪽도 함께 바꿔야 한다.
INDEX_CODES: dict[str, str] = {"kospi": "0001", "kosdaq": "1001", "kospi200": "2001"}
INDEX_LABELS: dict[str, str] = {"kospi": "코스피", "kosdaq": "코스닥", "kospi200": "코스피200"}

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT / "data" / "index_bars"
HEARTBEAT_PATH = BASE_DIR / "heartbeat.txt"

LOOKBACK_DAYS_IF_EMPTY = 365 * 3   # 캐시가 비어있을 때 처음 받아올 과거 범위(워치리스트 일봉 수집과 동일 관례)

TR_ID_INDEX_CHART = "FHKUP03500100"   # 국내주식업종기간별시세(일자별지수시세)


def write_heartbeat() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def issue_token(creds: KisCredentials) -> str:
    """build_account_status()/paper_trade_gdr.issue_access_token()와 동일한
    토큰 발급 패턴 — 한 번 호출해 전체 지수 3개에 재사용한다(레이트리밋 회피)."""
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_index_daily(creds: KisCredentials, token: str, index_code: str, start: str, end: str) -> list[OhlcvBar]:
    """일자별지수시세 조회 — output2를 OhlcvBar 리스트로 변환(오래된 날짜순 정렬).

    output1(현재가 스냅샷)은 여기서 쓰지 않는다 — 실시간 스냅샷은
    generate_dashboard.py의 build_index_strip()이 inquire-index-price로
    별도 조회한다(이 수집기는 "이력 캐시" 전용).
    """
    resp = requests.get(
        f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": TR_ID_INDEX_CHART,
            "custtype": "P",
        },
        params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": index_code,
            "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": end,
            "FID_PERIOD_DIV_CODE": "D",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("rt_cd") != "0":
        raise RuntimeError(data.get("msg1", "조회 실패").strip())

    bars = []
    for row in data.get("output2") or []:
        date = row.get("stck_bsop_date")
        if not date:
            continue
        bars.append(OhlcvBar(
            date=date,
            open=float(row.get("bstp_nmix_oprc") or 0.0),
            high=float(row.get("bstp_nmix_hgpr") or 0.0),
            low=float(row.get("bstp_nmix_lwpr") or 0.0),
            close=float(row.get("bstp_nmix_prpr") or 0.0),
            volume=int(float(row.get("acml_vol") or 0)),
        ))
    return sorted(bars, key=lambda b: b.date)


# 일자별지수시세는 실측 결과(2026-07-16) 요청 범위와 무관하게 호출 1회당
# 최대 50행만 돌려준다(공식 문서에 명시된 값이 아니라 이 세션에서 직접
# 확인한 제약) — 그래서 넓은 초기 백필 범위를 한 번에 요청해도 최근 50
# 거래일치만 얻고 나머지는 조용히 누락된다. fetch_index_daily_paginated()가
# 그 최근 페이지의 가장 이른 날짜 하루 전을 새 종료일로 삼아 반복 호출해서
# 이 누락을 메운다.
PAGE_SIZE_HINT = 50
MAX_BACKFILL_PAGES = 6   # 상한(약 300거래일) — 스파크라인이 필요로 하는 60거래일보다 넉넉한 여유


def fetch_index_daily_paginated(creds: KisCredentials, token: str, index_code: str, start: str, end: str) -> list[OhlcvBar]:
    """start~end 범위를 fetch_index_daily() 페이지네이션으로 최대한 채운다.

    한 페이지가 비거나, 반환된 가장 이른 날짜가 이미 start 이하이거나,
    페이지 크기가 PAGE_SIZE_HINT보다 작으면(더 이전 데이터가 없다는 뜻)
    중단한다. MAX_BACKFILL_PAGES로 무한루프를 방지한다.

    첫 페이지부터 실패하면 그대로 예외를 전파한다(collect_index()의
    try/except가 "실패"로 보고 — 기존 계약과 동일). 하지만 이미 한 페이지
    이상 성공한 뒤 다음 페이지에서 실패하면(KIS가 이 엔드포인트에서
    간헐적으로 500을 반환하는 것을 이 세션에서 실측) 예외를 전파하지 않고
    그때까지 모은 페이지를 그대로 반환한다 — 한 페이지 실패로 이미 받아둔
    나머지 페이지 데이터까지 통째로 버리지 않기 위함이다.
    """
    by_date: dict[str, OhlcvBar] = {}
    cur_end = end
    for _ in range(MAX_BACKFILL_PAGES):
        try:
            page = fetch_index_daily(creds, token, index_code, start, cur_end)
        except Exception:
            if by_date:
                break   # 이미 부분 성공 — 지금까지 모은 데이터를 살린다
            raise   # 첫 페이지부터 실패 — collect_index()에 실패로 보고
        if not page:
            break
        for b in page:
            by_date[b.date] = b
        earliest = page[0].date
        if earliest <= start or len(page) < PAGE_SIZE_HINT:
            break
        next_end = (dt.datetime.strptime(earliest, "%Y%m%d").date() - dt.timedelta(days=1)).strftime("%Y%m%d")
        if next_end >= cur_end:
            break   # 진행이 안 되면(날짜가 줄지 않으면) 무한루프 방지
        cur_end = next_end
    return sorted(by_date.values(), key=lambda b: b.date)


def collect_index(creds: KisCredentials, token: str, key: str, index_code: str, end: str) -> tuple[int, str | None]:
    """(신규 수집 봉 개수, 오류메시지) 반환 — 오류가 나도 예외를 던지지 않는다
    (collect_daily_bars_watchlist.collect_ticker와 동일한 실패 격리 계약)."""
    path = store_path(BASE_DIR, key)
    last = latest_date(path)
    if last is None:
        start = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS_IF_EMPTY)).strftime("%Y%m%d")
    else:
        start = (dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)).strftime("%Y%m%d")

    if start > end:
        return 0, None   # 이미 최신 상태

    try:
        bars = fetch_index_daily_paginated(creds, token, index_code, start, end)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"

    append_bars(path, bars)
    return len(bars), None


def main() -> None:
    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"KIS 인증정보 없음: {exc}")
        return

    try:
        token = issue_token(creds)
    except Exception as exc:
        print(f"KIS 토큰 발급 실패: {type(exc).__name__}: {exc}")
        return

    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")   # D-1까지만 — 룩어헤드 없음
    n_ok, n_new_bars, n_failed = 0, 0, 0
    for key, code in INDEX_CODES.items():
        count, error = collect_index(creds, token, key, code, end)
        if error:
            print(f"  {INDEX_LABELS[key]}({key}): 실패 ({error})")
            n_failed += 1
        else:
            print(f"  {INDEX_LABELS[key]}({key}): 신규 {count}봉")
            n_ok += 1
            n_new_bars += count

    print(f"\n지수 {len(INDEX_CODES)}개 중 {n_ok}개 성공(신규 {n_new_bars}봉), {n_failed}개 실패")
    write_heartbeat()


if __name__ == "__main__":
    main()
