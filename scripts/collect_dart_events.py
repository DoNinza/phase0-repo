#!/usr/bin/env python3
"""OpenDART 잠정실적 공시 point-in-time 이벤트 스토어 전체 수집 (PEAD Phase 3).

Phase 1 스파이크(scripts/spike_dart_events.py)는 표본 30건만 파싱했다 —
이 스크립트는 95종목 전체(EXPANDED_CANDIDATES)의 원본 잠정실적 공시
(정정 제외, §4.2)에 대해 실제로 영업이익·매출액 수치를 뽑아
data/dart_events/{ticker}.jsonl에 point-in-time으로 저장한다.

멱등·재개 가능: rcept_no 기준 이미 저장된 이벤트는 다시 원문을 받지
않는다(minute_bar_store와 동일한 append_events 중복제거 원칙) — 중간에
끊겨도 재실행하면 이어서 진행한다.

문서 하나당 원문(zip) 다운로드가 필요해 종목 수집보다 훨씬 느리다
(예상 이벤트 수 ~3,700건 × 호출당 정중한 대기 → 수십 분~1시간대 소요).

사용법: python scripts/collect_dart_events.py [--universe default|expanded]
                                                [--tickers T1,T2,...]
"""

from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

from phase0.config.dart_credentials import CredentialsMissingError, load_credentials
from phase0.data.candidate_batch import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.dart_ingest import (
    append_events,
    existing_rcept_nos,
    fetch_corp_code_map,
    fetch_disclosure_list,
    fetch_document_text,
    filter_original_filings,
    parse_filing_document,
    store_path,
)

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "data" / "dart_events"
HEARTBEAT_PATH = STORE_DIR / "heartbeat.txt"

BGN_DE = "20160101"


def write_heartbeat(msg: str) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(f"{dt.datetime.now().isoformat()} {msg}", encoding="utf-8")


def main() -> None:
    universe = "expanded"
    tickers_override: list[str] | None = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--universe":
            universe = args[i + 1]
        if a == "--tickers":
            tickers_override = args[i + 1].split(",")

    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"오류: {exc}")
        sys.exit(1)

    tickers = tickers_override or UNIVERSES[universe]
    end_de = dt.date.today().strftime("%Y%m%d")

    print(f"[1/3] corp_code 매핑 ({len(tickers)}종목)")
    full_map = fetch_corp_code_map(creds.api_key)
    corp_code_map = {t: full_map[t] for t in tickers if t in full_map}
    unmapped = [t for t in tickers if t not in full_map]
    print(f"  매핑 성공: {len(corp_code_map)}/{len(tickers)} (미매핑: {unmapped})")

    print(f"[2/3] 종목별 잠정실적 공시 조회 ({BGN_DE}~{end_de})")
    all_raw_events: list[dict] = []
    per_ticker_errors: dict[str, str] = {}
    for i, (ticker, corp_code) in enumerate(corp_code_map.items(), 1):
        try:
            raw = fetch_disclosure_list(creds.api_key, corp_code, bgn_de=BGN_DE, end_de=end_de)
        except Exception as exc:  # noqa: BLE001 — 종목 단위 격리
            per_ticker_errors[ticker] = str(exc)
            continue
        for ev in raw:
            ev["ticker"] = ticker
        all_raw_events.extend(raw)
        if i % 20 == 0 or i == len(corp_code_map):
            print(f"  {i}/{len(corp_code_map)}종목 조회 완료, 누적 원시 이벤트 {len(all_raw_events)}건")
        time.sleep(0.2)

    filtered = filter_original_filings(all_raw_events)
    print(f"  정정 배제·중복 제거 후 원본 이벤트: {len(filtered)}건")

    print("[3/3] 원문 파싱·저장 (이미 저장된 rcept_no는 건너뜀)")
    n_new, n_skipped, n_error, n_missing = 0, 0, 0, 0
    existing_by_path: dict[Path, set[str]] = {}
    for i, ev in enumerate(filtered, 1):
        path = store_path(STORE_DIR, ev["ticker"])
        if path not in existing_by_path:
            existing_by_path[path] = existing_rcept_nos(path)
        if ev["rcept_no"] in existing_by_path[path]:
            n_skipped += 1
            continue
        try:
            text = fetch_document_text(creds.api_key, ev["rcept_no"])
            parsed = parse_filing_document(text, ev)
        except Exception:  # noqa: BLE001 — 이벤트 단위 격리
            n_error += 1
            time.sleep(0.2)
            continue
        if parsed.parse_error is not None:
            n_missing += 1
        append_events(path, [parsed])
        existing_by_path[path].add(ev["rcept_no"])
        n_new += 1
        if n_new % 100 == 0:
            print(f"  진행: {i}/{len(filtered)} (신규 {n_new}, 건너뜀 {n_skipped}, "
                  f"결측/실패 {n_missing}, 오류 {n_error})")
            write_heartbeat(f"{i}/{len(filtered)}")
        time.sleep(0.2)

    print("\n" + "=" * 60)
    print(f"완료: 신규 저장 {n_new}건, 이미 있어 건너뜀 {n_skipped}건, "
          f"원본결측/파서실패 {n_missing}건, 네트워크 오류 {n_error}건")
    if per_ticker_errors:
        print(f"종목별 조회 실패({len(per_ticker_errors)}건): {per_ticker_errors}")
    print(f"저장 위치: {STORE_DIR}")
    write_heartbeat("done")


if __name__ == "__main__":
    main()
