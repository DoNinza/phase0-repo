"""Phase 1 데이터 스파이크 — OpenDART 잠정실적 공시 커버리지·파싱 가능성 실측.

docs/news_fundamentals_전략_기획안.md §8 Phase 1의 게이트 스크립트.
**수익률은 전혀 계산하지 않는다** — 이 단계는 순수하게 데이터 접근성만
잰다. 사전 선언된 게이트(§8):

  (a) EXPANDED_CANDIDATES 95종목 중 corp_code 매핑 성공 >= 90종목
  (b) 2016~2026 잠정실적 이벤트 총량 >= 300건
  (c) 원문 수치 파싱 성공률(표본 30건 기준) >= 90%

하나라도 미달이면 이 트랙을 여기서 중단하고 그 사실을 README에 기록한다
— 여기까지는 수익률 데이터를 전혀 안 보므로 중단해도 data snooping이
아니다(§8의 명시적 규약).

사용법:
    python scripts/spike_dart_events.py

산출물(전부 .gitignore 처리된 data/dart_spike/ 아래, 소스코드 아님):
    corp_code_map.json      — {ticker: corp_code} 매핑 결과
    events.json             — 식별된 잠정실적 이벤트 전체
    report_nm_variants.json — pblntf_ty=I 안에서 관측된 모든 고유 보고서명
                              (잠정실적 필터 패턴이 실제로 맞는지 육안 검토용)
    parse_samples.json      — 파싱 스파이크 표본 30건의 원문 파싱 결과
    gate_report.json        — 게이트 (a)/(b)/(c) 통과 여부 최종 판정
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

import requests

from phase0.config.dart_credentials import CredentialsMissingError, load_credentials
from phase0.data.candidate_batch import EXPANDED_CANDIDATES

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

BGN_DE = "20160101"
END_DE = time.strftime("%Y%m%d")

# 잠정실적(공정공시) 보고서명 식별 패턴 — 실제 표기는 "영업(잠정)실적"처럼
# "잠정"과 "실적" 사이에 괄호가 끼는 경우가 흔해 그 한 글자를 허용한다.
# 그래도 실제 변형은 report_nm_variants.json으로 전수 확인해야 한다
# (§8 "정확한 표기 변형은 Phase 1 스파이크에서 전수 확인").
PROVISIONAL_EARNINGS_PATTERN = re.compile(r"잠정\W{0,2}실적")

GATE_MIN_CORP_MAPPED = 90
GATE_MIN_EVENTS = 300
GATE_MIN_PARSE_RATE = 0.90
PARSE_SAMPLE_SIZE = 30

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "dart_spike"

Fetcher = Callable[..., requests.Response]


def _default_fetcher(url: str, params: dict) -> requests.Response:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp


@dataclass
class SpikeResult:
    corp_code_map: dict[str, str] = field(default_factory=dict)
    unmapped_tickers: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    report_nm_variants: dict[str, int] = field(default_factory=dict)
    per_ticker_errors: dict[str, str] = field(default_factory=dict)
    parse_samples: list[dict] = field(default_factory=list)


def fetch_corp_code_map(api_key: str, fetcher: Fetcher = _default_fetcher) -> dict[str, str]:
    """corpCode.xml(zip)을 받아 {6자리 종목코드: 8자리 corp_code} 매핑을 만든다.

    상장사가 아닌 corp_code(stock_code가 빈 문자열)는 제외한다.
    """
    resp = fetcher(CORP_CODE_URL, {"crtfc_key": api_key})
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)

    mapping: dict[str, str] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code:
            mapping[stock_code] = corp_code
    return mapping


def fetch_disclosure_list(
    api_key: str,
    corp_code: str,
    bgn_de: str = BGN_DE,
    end_de: str = END_DE,
    pblntf_ty: str = "I",
    fetcher: Fetcher = _default_fetcher,
) -> list[dict]:
    """corp_code 지정 시 3개월 제한이 풀리므로 10년치를 한 번에 조회한다
    (페이지당 최대 100건, 필요시 페이지네이션)."""
    events: list[dict] = []
    page_no = 1
    while True:
        resp = fetcher(
            LIST_URL,
            {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": pblntf_ty,
                "page_no": page_no,
                "page_count": 100,
            },
        )
        payload = resp.json()
        status = payload.get("status")
        if status == "013":  # 조회된 데이터가 없습니다
            break
        if status != "000":
            raise RuntimeError(f"DART list.json 오류 status={status} message={payload.get('message')}")

        page_events = payload.get("list", [])
        events.extend(page_events)

        total_page = int(payload.get("total_page", 1))
        if page_no >= total_page:
            break
        page_no += 1
        time.sleep(0.2)
    return events


def filter_provisional_earnings(events: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """report_nm에서 잠정실적 패턴을 찾는다. 매칭 여부와 무관하게 관측된 모든
    고유 report_nm(개수 포함)을 함께 반환 — 필터 패턴 자체가 맞는지 육안 검토용."""
    matched: list[dict] = []
    variants: dict[str, int] = {}
    for ev in events:
        name = ev.get("report_nm", "")
        variants[name] = variants.get(name, 0) + 1
        if PROVISIONAL_EARNINGS_PATTERN.search(name):
            matched.append(ev)
    return matched, variants


def fetch_document_text(api_key: str, rcept_no: str, fetcher: Fetcher = _default_fetcher) -> str:
    """공시서류원본(zip) 안의 모든 파일을 받아 텍스트로 이어붙인다.
    바이너리(pdf 등)가 섞여 있으면 디코딩 실패 파일은 건너뛴다."""
    resp = fetcher(DOCUMENT_URL, {"crtfc_key": api_key, "rcept_no": rcept_no})
    chunks: list[str] = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            raw = zf.read(name)
            try:
                chunks.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                try:
                    chunks.append(raw.decode("euc-kr"))
                except UnicodeDecodeError:
                    continue
    return "\n".join(chunks)


_TAG_RE = re.compile(r"<[^>]+>")
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_COLSPAN_RE = re.compile(r'colspan\s*=\s*"?(\d+)"?', re.IGNORECASE)

# 실제 DART "영업(잠정)실적(공정공시)" 원문 실측(2026-07-17) 결과, 표 서식이
# 연도별로 다르다는 게 확인됐다(기획안 §9.2가 경고한 그대로):
#   - 최근 서식(예: 2026년 삼성전자 공시): [구분(colspan2), 당기실적,
#     전기실적, 전기대비(colspan2: 증감율+흑자전환), 전년동기실적,
#     전년동기대비(colspan2: 증감율+흑자전환)] = 실제 셀 9개
#   - 과거 서식(예: 2018년 셀트리온 공시): 흑자전환 칼럼이 아예 없어
#     [구분(colspan2), 당기실적, 전기실적, 전기대비, 전년동기실적,
#     전년동기대비] = 실제 셀 7개
# 고정 인덱스로는 서식마다 깨지므로, 헤더 행의 "전년동기실적" 셀 위치를
# colspan을 반영해 "가상 컬럼 인덱스"로 계산하고, 그 인덱스를 데이터 행에
# 그대로 적용한다(데이터 행 자체는 colspan 없이 실제 셀 1개=가상 컬럼
# 1개인 것으로 실측 확인됨).
def _parse_num(cell: str) -> float | None:
    cell = cell.strip()
    if cell in ("", "-", "N/A"):
        return None
    try:
        return float(cell.replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def _row_cells_expanded(tr_inner: str) -> list[str]:
    cells: list[str] = []
    for attrs, raw in _TD_RE.findall(tr_inner):
        text = " ".join(_TAG_RE.sub(" ", raw).split())
        span_match = _COLSPAN_RE.search(attrs)
        span = int(span_match.group(1)) if span_match else 1
        cells.extend([text] * span)
    return cells


def attempt_parse_figures(document_text: str) -> dict:
    """원문 표에서 영업이익(당해실적) 행의 당기실적·전년동기실적을 뽑는다.

    표 서식이 회사·연도별로 다를 수 있다는 게 기획안 §9.2의 경고라, 고정
    인덱스 대신 헤더의 "전년동기실적" 위치를 매 표마다 다시 찾는다.

    실패를 두 종류로 구분해서 반환한다(원문 실측 결과 이 구분이 실제로
    필요했다 — 표/행을 못 찾는 "진짜 파서 결함"과, 표·행은 정상 발견됐지만
    원본 자체가 "-"(예: 합병 등으로 전년동기와 직접 비교 불가)인 "정당한
    결측"은 성격이 다르다):
      - {"skip_reason": "table_or_row_not_found"} — 표/헤더/행 자체를 못 찾음
      - {"skip_reason": "source_data_missing"} — 행은 찾았지만 값이 "-" 등
      - 성공 시 {"op_income_current": float, "op_income_prior_year_same_q": float}
    """
    for table_match in _TABLE_RE.finditer(document_text):
        table_html = table_match.group(1)
        if "영업이익" not in table_html or "전년동기실적" not in table_html:
            continue

        rows = [_row_cells_expanded(tr.group(1)) for tr in _TR_RE.finditer(table_html)]

        header_col = next(
            (row.index("전년동기실적") for row in rows if "전년동기실적" in row), None
        )
        if header_col is None:
            continue

        for row in rows:
            if len(row) > max(2, header_col) and row[0] == "영업이익" and row[1] == "당해실적":
                current = _parse_num(row[2])
                prior_year_same_q = _parse_num(row[header_col])
                if current is None or prior_year_same_q is None:
                    return {"skip_reason": "source_data_missing"}
                return {
                    "op_income_current": current,
                    "op_income_prior_year_same_q": prior_year_same_q,
                }
    return {"skip_reason": "table_or_row_not_found"}


def run_spike(api_key: str, fetcher: Fetcher = _default_fetcher) -> SpikeResult:
    result = SpikeResult()

    print(f"[1/4] corp_code 매핑 (전체 상장사 → {len(EXPANDED_CANDIDATES)}종목)")
    full_map = fetch_corp_code_map(api_key, fetcher)
    for ticker in EXPANDED_CANDIDATES:
        if ticker in full_map:
            result.corp_code_map[ticker] = full_map[ticker]
        else:
            result.unmapped_tickers.append(ticker)
    print(f"  매핑 성공: {len(result.corp_code_map)}/{len(EXPANDED_CANDIDATES)}"
          f" (미매핑: {result.unmapped_tickers})")

    print(f"[2/4] 종목별 잠정실적 공시 조회 ({BGN_DE}~{END_DE}, pblntf_ty=I)")
    for i, (ticker, corp_code) in enumerate(result.corp_code_map.items(), 1):
        try:
            events = fetch_disclosure_list(api_key, corp_code, fetcher=fetcher)
        except Exception as exc:  # noqa: BLE001 — 종목 단위 격리, candidate_batch.py와 동일 원칙
            result.per_ticker_errors[ticker] = str(exc)
            continue
        matched, variants = filter_provisional_earnings(events)
        for m in matched:
            m["ticker"] = ticker
        result.events.extend(matched)
        for name, count in variants.items():
            result.report_nm_variants[name] = result.report_nm_variants.get(name, 0) + count
        if i % 20 == 0 or i == len(result.corp_code_map):
            print(f"  {i}/{len(result.corp_code_map)}종목 처리, 누적 이벤트 {len(result.events)}건")
        time.sleep(0.2)

    print(f"[3/4] 원문 파싱 스파이크 (표본 {PARSE_SAMPLE_SIZE}건)")
    sample = result.events[:: max(1, len(result.events) // PARSE_SAMPLE_SIZE)][:PARSE_SAMPLE_SIZE]
    for ev in sample:
        rcept_no = ev["rcept_no"]
        try:
            text = fetch_document_text(api_key, rcept_no, fetcher)
            parsed = attempt_parse_figures(text)
        except Exception as exc:  # noqa: BLE001
            result.parse_samples.append(
                {"rcept_no": rcept_no, "ticker": ev["ticker"], "error": str(exc)}
            )
            time.sleep(0.2)
            continue
        entry = {"rcept_no": rcept_no, "ticker": ev["ticker"], **parsed}
        result.parse_samples.append(entry)
        time.sleep(0.2)

    print("[4/4] 완료")
    return result


def build_gate_report(result: SpikeResult) -> dict:
    n_mapped = len(result.corp_code_map)
    n_events = len(result.events)

    n_sampled = len(result.parse_samples)
    n_parsed_ok = sum(1 for s in result.parse_samples if "op_income_current" in s)
    n_source_missing = sum(
        1 for s in result.parse_samples if s.get("skip_reason") == "source_data_missing"
    )
    n_not_found = sum(
        1 for s in result.parse_samples if s.get("skip_reason") == "table_or_row_not_found"
    )
    n_fetch_error = sum(1 for s in result.parse_samples if "error" in s)

    # §8에 사전등록된 문구 그대로("수치 파싱 성공률") — 원본 자체가 "-"인
    # 정당한 결측도 여기서는 엄격하게 실패로 센다. 게이트 판정은 이 엄격한
    # 정의를 그대로 쓴다(사후에 유리하게 재정의하지 않는다).
    parse_rate = (n_parsed_ok / n_sampled) if n_sampled else 0.0
    # 참고용 보조 지표 — 표/헤더/행을 못 찾은 "진짜 파서 결함"만 분모로 삼은
    # 비율(원문 실측 결과 이 구분이 실제로 의미가 있었다: §8 산출물 참고,
    # 최종 통과/중단 판단은 사람이 위 엄격한 parse_rate와 함께 본다).
    n_attempted_with_row_found = n_sampled - n_not_found - n_fetch_error
    parser_success_rate_excl_missing_source = (
        (n_parsed_ok / n_attempted_with_row_found) if n_attempted_with_row_found else 0.0
    )

    gate_a = n_mapped >= GATE_MIN_CORP_MAPPED
    gate_b = n_events >= GATE_MIN_EVENTS
    gate_c = parse_rate >= GATE_MIN_PARSE_RATE

    return {
        "gate_a_corp_mapping": {
            "threshold": GATE_MIN_CORP_MAPPED,
            "actual": n_mapped,
            "passed": gate_a,
        },
        "gate_b_event_count": {
            "threshold": GATE_MIN_EVENTS,
            "actual": n_events,
            "passed": gate_b,
        },
        "gate_c_parse_rate": {
            "threshold": GATE_MIN_PARSE_RATE,
            "actual": round(parse_rate, 4),
            "n_sampled": n_sampled,
            "n_parsed_ok": n_parsed_ok,
            "n_source_data_missing": n_source_missing,
            "n_table_or_row_not_found": n_not_found,
            "n_fetch_error": n_fetch_error,
            "passed": gate_c,
            "note": (
                "이 passed는 §8에 사전등록된 엄격한 정의(원본 '-' 결측도 실패로 "
                "카운트)를 그대로 적용한 결과다. parser_success_rate_excl_missing_source"
                "는 표/헤더/행을 실제로 못 찾은 경우만 분모로 삼은 참고 지표 — "
                "표·행을 찾은 경우엔 값 추출이 항상 성공했는지를 따로 보여준다."
            ),
            "parser_success_rate_excl_missing_source": round(
                parser_success_rate_excl_missing_source, 4
            ),
        },
        "all_gates_passed": gate_a and gate_b and gate_c,
    }


def main() -> None:
    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"오류: {exc}")
        sys.exit(1)

    result = run_spike(creds.api_key)
    gate_report = build_gate_report(result)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "corp_code_map.json").write_text(
        json.dumps(result.corp_code_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "events.json").write_text(
        json.dumps(result.events, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "report_nm_variants.json").write_text(
        json.dumps(result.report_nm_variants, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "parse_samples.json").write_text(
        json.dumps(result.parse_samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "gate_report.json").write_text(
        json.dumps(gate_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("게이트 판정 (§8)")
    print("=" * 60)
    for key in ("gate_a_corp_mapping", "gate_b_event_count", "gate_c_parse_rate"):
        g = gate_report[key]
        mark = "PASS" if g["passed"] else "FAIL"
        print(f"  [{mark}] {key}: {g}")
    print(f"\n최종: {'전체 통과 — Phase 2로 진행 가능' if gate_report['all_gates_passed'] else '미달 항목 있음 — §8 규약대로 중단·README 기록 검토'}")
    if result.per_ticker_errors:
        print(f"\n종목별 조회 실패({len(result.per_ticker_errors)}건): {result.per_ticker_errors}")
    print(f"\n산출물: {OUT_DIR}")


if __name__ == "__main__":
    main()
