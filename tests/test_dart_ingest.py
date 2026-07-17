"""phase0/data/dart_ingest.py 검증 — 전부 fetcher 주입/합성 데이터로,
네트워크 호출 없음(이 저장소의 기존 원칙, pykrx_ingest 테스트와 동일 패턴).

표 파싱 픽스처(신형/구형 서식)는 Phase 1 스파이크(2026-07-17)에서 실제
DART 원문으로 검증한 두 형태를 그대로 축약해 담았다 — 진짜 원문 구조를
반영한 것이지 임의로 지어낸 표가 아니다.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from phase0.data.dart_ingest import (
    DartEvent,
    append_events,
    existing_rcept_nos,
    fetch_corp_code_map,
    fetch_disclosure_list,
    fetch_document_text,
    filter_original_filings,
    load_events,
    parse_filing_document,
    store_path,
)

# --- corp_code 매핑 -----------------------------------------------------

def test_fetch_corp_code_map_excludes_unlisted():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<result>
<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
<list><corp_code>00164779</corp_code><corp_name>비상장회사</corp_name><stock_code> </stock_code><modify_date>20260101</modify_date></list>
</result>""".encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml_content)

    class FakeResp:
        content = buf.getvalue()

    def fake_fetcher(url, params):
        assert params["crtfc_key"] == "fake_key"
        return FakeResp()

    result = fetch_corp_code_map("fake_key", fetcher=fake_fetcher)
    assert result == {"005930": "00126380"}


# --- 공시검색 페이지네이션 -------------------------------------------------

def test_fetch_disclosure_list_paginates():
    pages = {
        1: {"status": "000", "total_page": 2, "list": [{"rcept_no": "1"}]},
        2: {"status": "000", "total_page": 2, "list": [{"rcept_no": "2"}]},
    }

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_fetcher(url, params):
        return FakeResp(pages[int(params["page_no"])])

    events = fetch_disclosure_list("key", "00126380", fetcher=fake_fetcher)
    assert [e["rcept_no"] for e in events] == ["1", "2"]


def test_fetch_disclosure_list_no_data_returns_empty():
    class FakeResp:
        def json(self):
            return {"status": "013", "message": "조회된 데이터가 없습니다"}

    events = fetch_disclosure_list("key", "00126380", fetcher=lambda url, params: FakeResp())
    assert events == []


# --- 정정공시 배제 + 종목·날짜 중복 제거 ----------------------------------

def test_filter_original_filings_drops_amendments_and_non_matching():
    events = [
        {"ticker": "005930", "rcept_dt": "20210601", "rcept_no": "1",
         "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)"},
        {"ticker": "005930", "rcept_dt": "20210602", "rcept_no": "2",
         "report_nm": "분기보고서"},
        {"ticker": "005930", "rcept_dt": "20210603", "rcept_no": "3",
         "report_nm": "[기재정정]연결재무제표기준영업(잠정)실적(공정공시)"},
    ]
    result = filter_original_filings(events)
    assert [e["rcept_no"] for e in result] == ["1"]


def test_filter_original_filings_prefers_consolidated_on_same_day():
    events = [
        {"ticker": "005930", "rcept_dt": "20210601", "rcept_no": "1",
         "report_nm": "영업(잠정)실적(공정공시)"},
        {"ticker": "005930", "rcept_dt": "20210601", "rcept_no": "2",
         "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)"},
    ]
    result = filter_original_filings(events)
    assert len(result) == 1
    assert result[0]["rcept_no"] == "2"


def test_filter_original_filings_keeps_distinct_dates():
    events = [
        {"ticker": "005930", "rcept_dt": "20210601", "rcept_no": "1",
         "report_nm": "영업(잠정)실적(공정공시)"},
        {"ticker": "005930", "rcept_dt": "20210901", "rcept_no": "2",
         "report_nm": "영업(잠정)실적(공정공시)"},
    ]
    result = filter_original_filings(events)
    assert len(result) == 2


# --- 원문 표 파싱: 신형(2026, 흑자전환 칼럼 있음)/구형(2018, 없음) --------

_MODERN_TABLE_FIXTURE = """
<table>
<tbody>
<tr>
<td colspan="2" rowspan="2">구분</td>
<td>당기실적</td><td>전기실적</td>
<td colspan="2">전기대비</td>
<td>전년동기실적</td>
<td colspan="2">전년동기대비</td>
</tr>
<tr>
<td>(26.2Q)</td><td>(26.1Q)</td><td>증감율(%)</td><td>흑자적자전환여부</td>
<td>(25.2Q)</td><td>증감율(%)</td><td>흑자적자전환여부</td>
</tr>
<tr>
<td rowspan="2">매출액</td><td>당해실적</td>
<td>171.00</td><td>133.87</td><td>27.74</td><td>-</td>
<td>74.57</td><td>129.31</td><td>-</td>
</tr>
<tr><td>누계실적</td><td>304.87</td><td>-</td><td>-</td><td>-</td><td>153.71</td><td>98.34</td><td>-</td></tr>
<tr>
<td rowspan="2">영업이익</td><td>당해실적</td>
<td>89.40</td><td>57.23</td><td>56.21</td><td>-</td>
<td>4.68</td><td>1810.26</td><td>-</td>
</tr>
</tbody>
</table>
"""

_OLD_TABLE_FIXTURE = """
<table>
<tbody>
<tr>
<td colspan="2">구분</td>
<td>당기실적</td><td>전기실적</td><td>전기대비증감율(%)</td>
<td>전년동기실적</td><td>전년동기대비증감율(%)</td>
</tr>
<tr>
<td>(2018.1Q)</td><td>(2017.4Q)</td><td></td><td>(2017.1Q)</td><td></td>
</tr>
<tr>
<td rowspan="2">매출액</td><td>당해실적</td>
<td>220,474</td><td>236,130</td><td>-6.6</td>
<td>175,833</td><td>+25.4</td>
</tr>
<tr><td>누계실적</td><td>220,474</td><td>-</td><td>-</td><td>175,833</td><td>+25.4</td></tr>
<tr>
<td rowspan="2">영업이익</td><td>당해실적</td>
<td>116,681</td><td>158,989</td><td>-26.6</td>
<td>90,788</td><td>+28.5</td>
</tr>
</tbody>
</table>
"""

_MISSING_DATA_FIXTURE = """
<table>
<tbody>
<tr><td colspan="2">구분</td><td>당기실적</td><td>전기실적</td><td>전기대비</td>
<td>전년동기실적</td><td>전년동기대비</td></tr>
<tr>
<td rowspan="2">영업이익</td><td>당해실적</td>
<td>-434,814</td><td>-89,144</td><td>-387.8%</td>
<td>-</td><td>-</td>
</tr>
</tbody>
</table>
"""


def test_parse_filing_document_modern_schema():
    ev = {"ticker": "005930", "corp_code": "00126380", "rcept_no": "1",
          "rcept_dt": "20260707", "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)"}
    result = parse_filing_document(_MODERN_TABLE_FIXTURE, ev)
    assert result.op_income_current == 89.4
    assert result.op_income_prior_year_same_q == 4.68
    assert result.sales_current == 171.0
    assert result.sales_prior_year_same_q == 74.57
    assert result.parse_error is None


def test_parse_filing_document_old_schema_no_turnaround_column():
    ev = {"ticker": "068270", "corp_code": "00126000", "rcept_no": "2",
          "rcept_dt": "20180509", "report_nm": "영업(잠정)실적(공정공시)"}
    result = parse_filing_document(_OLD_TABLE_FIXTURE, ev)
    assert result.op_income_current == 116681.0
    assert result.op_income_prior_year_same_q == 90788.0
    assert result.sales_current == 220474.0
    assert result.sales_prior_year_same_q == 175833.0


def test_parse_filing_document_missing_source_data():
    ev = {"ticker": "028260", "corp_code": "00164742", "rcept_no": "3",
          "rcept_dt": "20160427", "report_nm": "영업(잠정)실적(공정공시)"}
    result = parse_filing_document(_MISSING_DATA_FIXTURE, ev)
    assert result.op_income_current is None
    assert result.op_income_prior_year_same_q is None
    assert result.sales_current is None  # 매출액 행 자체가 이 픽스처엔 없음


def test_fetch_document_text_decodes_and_joins_zip_members():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.xml", "<p>영업이익</p>".encode("utf-8"))

    class FakeResp:
        content = buf.getvalue()

    text = fetch_document_text("key", "123", fetcher=lambda url, params: FakeResp())
    assert "영업이익" in text


# --- point-in-time 저장소 ------------------------------------------------

def test_append_and_load_events_roundtrip(tmp_path: Path):
    path = store_path(tmp_path, "005930")
    events = [
        DartEvent(ticker="005930", corp_code="00126380", rcept_no="1",
                  rcept_dt="20210601", report_nm="영업(잠정)실적(공정공시)",
                  op_income_current=1.0, op_income_prior_year_same_q=0.5),
    ]
    append_events(path, events)
    loaded = load_events(path)
    assert loaded == events


def test_append_events_dedups_by_rcept_no(tmp_path: Path):
    path = store_path(tmp_path, "005930")
    ev = DartEvent(ticker="005930", corp_code="00126380", rcept_no="1",
                    rcept_dt="20210601", report_nm="x")
    append_events(path, [ev])
    append_events(path, [ev])
    assert len(load_events(path)) == 1


def test_existing_rcept_nos_empty_for_missing_file(tmp_path: Path):
    assert existing_rcept_nos(tmp_path / "nope.jsonl") == set()
