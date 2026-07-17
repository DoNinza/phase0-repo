"""OpenDART 잠정실적 공시 수집·파싱·point-in-time 저장 (PEAD Phase 3).

Phase 1 스파이크(scripts/spike_dart_events.py)에서 실측 검증한 로직을
프로덕션 모듈로 옮긴 것 — HTTP 호출은 fetcher를 주입받는 구조라 네트워크
없이 pytest로 검증 가능하다(이 저장소의 기존 원칙, pykrx_ingest.py와
동일 패턴).

핵심 설계는 docs/news_fundamentals_전략_기획안.md §4를 그대로 따른다:
  - **look-ahead 방지**: DART 공시검색 응답엔 접수 시각이 없고 날짜
    (rcept_dt)만 있다 — 그래서 이벤트 자체엔 시각 정보를 만들어내지
    않는다. "D+1 시가 진입" 규칙은 신호 함수(phase0.strategy.pead) 쪽
    책임이다.
  - **정정공시 배제**: report_nm에 [기재정정]/[첨부추가]/[첨부정정] 등
    대괄호 태그가 붙은 건 최초 접수분이 아니다 — 원본만 남긴다(§4.2).
  - **같은 날 중복 신고 처리**: 연결/별도(개별) 재무제표 기준을 같은 날
    동시에 신고하는 경우가 실측으로 확인됐다 — 종목당 하루에 하나만
    남기고, 연결 기준이 있으면 그걸 우선한다(더 완전한 그림이므로).
"""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

import requests

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"

BGN_DE = "20160101"

# 잠정실적(공정공시) 보고서명 식별 패턴 — Phase 1 스파이크에서 25개 실제
# 변형을 전수 확인(report_nm_variants.json), 전부 진짜 잠정실적 계열이었음.
PROVISIONAL_EARNINGS_PATTERN = re.compile(r"잠정\W{0,2}실적")
# 정정·첨부 태그 — 이게 붙으면 최초 접수분이 아니다(§4.2).
AMENDMENT_TAG_PATTERN = re.compile(r"^\[(기재정정|첨부추가|첨부정정|첨부변경)\]")

Fetcher = Callable[..., requests.Response]


def _default_fetcher(url: str, params: dict) -> requests.Response:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp


@dataclass
class DartEvent:
    """point-in-time 이벤트 하나 — data/dart_events/<ticker>.jsonl에 저장.

    op_income_*/sales_*가 None이면 원본 자체에 값이 없었던 것(정당한
    결측, Phase 1 §10 참고)이지 파싱 실패가 아니다 — parse_error 필드가
    실제 파서 결함(표/헤더/행 자체를 못 찾음)을 구분해서 담는다.
    """

    ticker: str
    corp_code: str
    rcept_no: str
    rcept_dt: str  # YYYYMMDD — 접수'일자'만 있음(시각 없음, 위 docstring 참고)
    report_nm: str
    op_income_current: float | None = None
    op_income_prior_year_same_q: float | None = None
    sales_current: float | None = None
    sales_prior_year_same_q: float | None = None
    parse_error: str | None = None  # "table_or_row_not_found" 등


def fetch_corp_code_map(api_key: str, fetcher: Fetcher = _default_fetcher) -> dict[str, str]:
    """corpCode.xml(zip)을 받아 {6자리 종목코드: 8자리 corp_code} 매핑을 만든다."""
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
    end_de: str | None = None,
    pblntf_ty: str = "I",
    fetcher: Fetcher = _default_fetcher,
) -> list[dict]:
    """corp_code 지정 시 3개월 제한이 풀리므로 전체 구간을 한 번에 조회한다
    (페이지당 최대 100건, 필요시 페이지네이션)."""
    end_de = end_de or time.strftime("%Y%m%d")
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

        events.extend(payload.get("list", []))

        total_page = int(payload.get("total_page", 1))
        if page_no >= total_page:
            break
        page_no += 1
        time.sleep(0.2)
    return events


def filter_original_filings(events: list[dict]) -> list[dict]:
    """잠정실적 패턴 매칭 + 정정공시 배제 + 종목·날짜 중복 제거(§4.2).

    같은 (ticker, rcept_dt)에 여러 건이 남으면 report_nm에 "연결"이 있는
    쪽을 우선하고, 없으면 먼저 나온 것을 쓴다.
    """
    provisional = [
        ev for ev in events
        if PROVISIONAL_EARNINGS_PATTERN.search(ev.get("report_nm", ""))
        and not AMENDMENT_TAG_PATTERN.search(ev.get("report_nm", ""))
    ]

    by_key: dict[tuple[str, str], dict] = {}
    for ev in provisional:
        key = (ev["ticker"], ev["rcept_dt"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = ev
        elif "연결" in ev.get("report_nm", "") and "연결" not in existing.get("report_nm", ""):
            by_key[key] = ev
    return list(by_key.values())


def fetch_document_text(api_key: str, rcept_no: str, fetcher: Fetcher = _default_fetcher) -> str:
    """공시서류원본(zip) 안의 모든 파일을 받아 텍스트로 이어붙인다."""
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


def _extract_labeled_row_figures(document_text: str, label: str) -> tuple[float, float] | None:
    """DART 잠정실적 표에서 `label`(예: "영업이익", "매출액") 행의 당해실적
    당기·전년동기 수치를 뽑는다. 표 서식이 연도별로 다르다는 게 Phase 1
    실측 결과라(예: 옛 서식엔 흑자전환여부 칼럼이 없음), 고정 인덱스 대신
    헤더의 "전년동기실적" 위치를 colspan 반영해 매 표마다 동적으로 찾는다.

    반환: (당기, 전년동기) 성공 시. 표/헤더/행 자체를 못 찾거나 값이
    "-"(원본 결측)이면 None — 호출부가 두 실패를 구분해 기록한다.
    """
    for table_match in _TABLE_RE.finditer(document_text):
        table_html = table_match.group(1)
        if label not in table_html or "전년동기실적" not in table_html:
            continue

        rows = [_row_cells_expanded(tr.group(1)) for tr in _TR_RE.finditer(table_html)]

        header_col = next(
            (row.index("전년동기실적") for row in rows if "전년동기실적" in row), None
        )
        if header_col is None:
            continue

        for row in rows:
            if len(row) > max(2, header_col) and row[0] == label and row[1] == "당해실적":
                current = _parse_num(row[2])
                prior = _parse_num(row[header_col])
                if current is None or prior is None:
                    return None
                return (current, prior)
    return None


def parse_filing_document(document_text: str, ev: dict) -> DartEvent:
    """공시 원문에서 영업이익·매출액 당기/전년동기를 함께 뽑아 DartEvent로."""
    op = _extract_labeled_row_figures(document_text, "영업이익")
    sales = _extract_labeled_row_figures(document_text, "매출액")

    parse_error = None
    if op is None and sales is None:
        parse_error = "값 없음(원본 결측 또는 표 미검출 — 둘 다 실패)"

    return DartEvent(
        ticker=ev["ticker"],
        corp_code=ev["corp_code"],
        rcept_no=ev["rcept_no"],
        rcept_dt=ev["rcept_dt"],
        report_nm=ev["report_nm"],
        op_income_current=op[0] if op else None,
        op_income_prior_year_same_q=op[1] if op else None,
        sales_current=sales[0] if sales else None,
        sales_prior_year_same_q=sales[1] if sales else None,
        parse_error=parse_error,
    )


# ---------------------------------------------------------------------------
# point-in-time 저장소 — minute_bar_store.py와 동일한 JSONL append-only 패턴
# ---------------------------------------------------------------------------

def store_path(base_dir: Path, ticker: str) -> Path:
    return base_dir / f"{ticker}.jsonl"


def existing_rcept_nos(path: Path) -> set[str]:
    if not path.exists():
        return set()
    nos = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nos.add(json.loads(line)["rcept_no"])
    return nos


def append_events(path: Path, events: list[DartEvent]) -> None:
    """rcept_no 기준 중복은 걸러내고 append."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = existing_rcept_nos(path)
    with path.open("a", encoding="utf-8") as f:
        for ev in events:
            if ev.rcept_no in existing:
                continue
            existing.add(ev.rcept_no)
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")


def load_events(path: Path) -> list[DartEvent]:
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(DartEvent(**json.loads(line)))
    return events
