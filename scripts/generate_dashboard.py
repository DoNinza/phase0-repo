#!/usr/bin/env python3
"""GDR 페이퍼 트레이딩 대시보드 HTML 생성 (2026-07-15).

data/paper_trading/gdr_trades.jsonl(+heartbeat.txt)을 읽어 자기완결형
HTML 대시보드를 만든다. 실시간 서버가 아니라 스냅샷 생성 방식 — cron으로
주기적으로 재실행하고 Artifact를 재배포하는 방식으로 "거의 실시간" 갱신을
흉내낸다(README "페이퍼 트레이딩 인프라" 참고).

사용법: python scripts/generate_dashboard.py [출력경로]
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    # 이 스크립트를 `python scripts/generate_dashboard.py`로 직접 실행하면
    # sys.path[0]이 scripts/ 자신이라 형제 스크립트(collect_*)를
    # "scripts.X"로 임포트할 수 없다(pytest는 rootdir를 자동으로 넣어주지만
    # 직접 실행은 아니다) — 그래서 저장소 루트를 명시적으로 추가한다.
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

import requests

from phase0.backtest.preregistered_results import ALL_RESULT_SETS
from phase0.bootstrap.cluster_bootstrap import DailyRecord, moving_block_bootstrap
from phase0.config.kis_credentials import CredentialsMissingError, load_credentials
from phase0.config.kiwoom_credentials import load_credentials as load_kiwoom_credentials
from phase0.data.bar_resample import resample_monthly, resample_weekly
from phase0.data.daily_bar_store import load_bars as load_daily_bars, store_path as daily_store_path
from phase0.data.minute_bar_store import load_bars
from phase0.data.pykrx_ingest import OhlcvBar, fetch_ohlcv
from phase0.paper.account_snapshots import (
    AccountSnapshot, append_snapshot, latest_per_date, load_snapshots,
)
from phase0.paper.alerts import append_alert, diff_states, load_alerts
from phase0.paper.trade_log import (
    consecutive_losses, current_drawdown, daily_return, load_entries, monthly_return,
    weekly_return,
)
from phase0.risk.circuit_breaker import CircuitBreakerConfig, check_halt
from phase0.risk.metrics import (
    MIN_DAYS_FOR_RATIO, MIN_DAYS_FOR_VAR, daily_pnl_series, historical_var, sharpe_ratio,
    sortino_ratio,
)
from phase0.strategy.gap_rebound import (
    ATR_BAND, GAP_CAP, MIN_HISTORY, PREV_DAY_CRASH, TREND_FLOOR, evaluate_conditions,
)
from scripts.collect_daily_bars_watchlist import BASE_DIR as DAILY_BARS_DIR, WATCHLIST
from scripts.collect_index_bars import BASE_DIR as INDEX_BARS_DIR, INDEX_CODES, INDEX_LABELS
from scripts.collect_minute_bars_kiwoom import fetch_ticker_bars as fetch_kiwoom_minute_bars, issue_token as issue_kiwoom_token

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "paper_trading" / "gdr_trades.jsonl"
HEARTBEAT_PATH = REPO_ROOT / "data" / "paper_trading" / "heartbeat.txt"
ETF_LOG_PATH = REPO_ROOT / "data" / "paper_trading_etf" / "gdr_trades.jsonl"
ACCOUNT_SNAPSHOTS_PATH = REPO_ROOT / "data" / "paper_trading" / "account_snapshots.jsonl"
ALERTS_LOG_PATH = REPO_ROOT / "data" / "paper_trading" / "alerts.jsonl"
# 상태전환 감지(diff_states)용 "직전 실행 상태" 스냅샷 — JSONL 누적이 아니라
# 매번 덮어쓰는 단일 JSON 파일이다(account_snapshots.jsonl과 달리 이력 자체가
# 필요 없고 "바로 직전 값"만 있으면 된다).
DASHBOARD_STATE_PATH = REPO_ROOT / "data" / "paper_trading" / "dashboard_state.json"
TEMPLATE_PATH = REPO_ROOT / "scripts" / "dashboard_template.html"
DEFAULT_OUT_PATH = REPO_ROOT / "data" / "paper_trading" / "dashboard.html"

# 전략 현황 보드용 — 사전등록된 챔피언 파라미터를 여기서 재선언하지 않고
# 그대로 문자열로 echo만 한다(paper_trade_gdr.py/paper_trade_etf_gdr.py의
# F_FILL/K_STOP이 단일 진실 공급원 — 결과 보고 다시 고르지 않는다는 원칙).
STRATEGIES = [
    {"key": "kr", "label": "GDR-KR", "log_path": LOG_PATH,
     "config_note": "f_fill=1.0, k_stop=1.0 (95종목 사전등록 챔피언)"},
    {"key": "etf", "label": "GDR-ETF", "log_path": ETF_LOG_PATH,
     "config_note": "f_fill=1.0, k_stop=1.0 (59개 ETF 사전등록 챔피언)"},
]

US_MINUTE_BARS_DIR = REPO_ROOT / "data" / "minute_bars_us"
US_MINUTE_HEARTBEAT_PATH = US_MINUTE_BARS_DIR / "heartbeat.txt"

# B6 "데이터·시스템" 파이프라인 상태 표용 경로들. 각 하트비트 경로는 실제로
# 그 파일을 쓰는 수집 스크립트를 읽어서 확인한 값이다(추측 금지):
# collect_daily_bars_watchlist.py / collect_minute_bars.py /
# collect_minute_bars_kiwoom.py의 HEARTBEAT_PATH, 그리고 위 LOG_PATH/
# ETF_LOG_PATH와 짝을 이루는 paper_trade_gdr.py / paper_trade_etf_gdr.py의
# HEARTBEAT_PATH.
DAILY_BARS_HEARTBEAT_PATH = DAILY_BARS_DIR / "heartbeat.txt"
MINUTE_BARS_DIR = REPO_ROOT / "data" / "minute_bars"
MINUTE_BARS_HEARTBEAT_PATH = MINUTE_BARS_DIR / "heartbeat.txt"
KIWOOM_MINUTE_BARS_DIR = REPO_ROOT / "data" / "minute_bars_kiwoom"
KIWOOM_MINUTE_HEARTBEAT_PATH = KIWOOM_MINUTE_BARS_DIR / "heartbeat.txt"
ETF_PAPER_TRADING_DIR = REPO_ROOT / "data" / "paper_trading_etf"
ETF_HEARTBEAT_PATH = ETF_PAPER_TRADING_DIR / "heartbeat.txt"

# 상단 헤더 하트비트 점(dashboard_template.html)이 쓰는 "96시간 지나면
# 회색(stale)" 기준을 그대로 재사용한다 — 새 임계값을 발명하지 않는다.
STALE_HOURS_THRESHOLD = 96

SYSTEM_HEALTH_PIPELINES = [
    {"key": "daily_bars", "label": "워치리스트 일봉 캐시",
     "dir_path": DAILY_BARS_DIR, "heartbeat_path": DAILY_BARS_HEARTBEAT_PATH},
    {"key": "minute_bars", "label": "국내 분봉(KIS, 당일)",
     "dir_path": MINUTE_BARS_DIR, "heartbeat_path": MINUTE_BARS_HEARTBEAT_PATH},
    {"key": "minute_bars_kiwoom", "label": "국내 분봉(키움 백필)",
     "dir_path": KIWOOM_MINUTE_BARS_DIR, "heartbeat_path": KIWOOM_MINUTE_HEARTBEAT_PATH},
    {"key": "minute_bars_us", "label": "미국 분봉(yfinance)",
     "dir_path": US_MINUTE_BARS_DIR, "heartbeat_path": US_MINUTE_HEARTBEAT_PATH},
    {"key": "paper_trading", "label": "페이퍼 트레이딩(GDR-KR)",
     "dir_path": LOG_PATH.parent, "heartbeat_path": HEARTBEAT_PATH},
    {"key": "paper_trading_etf", "label": "페이퍼 트레이딩(GDR-ETF)",
     "dir_path": ETF_PAPER_TRADING_DIR, "heartbeat_path": ETF_HEARTBEAT_PATH},
]

TR_ID_BALANCE = {"prod": "TTTC8434R", "vps": "VTTC8434R"}

MINUTE_MAX_CALLS_FOR_HELD = 10   # 보유종목 분봉 즉석조회 상한(900개x10=9000봉, 약 4~5개월)
DAILY_LOOKBACK_DAYS_FOR_UNCACHED_HOLDING = 365 * 3

# 워치리스트(candidate_batch.DEFAULT_CANDIDATES + etf_candidates.DEFAULT_CANDIDATES)
# 종목명 — pykrx의 종목명 조회 함수가 깨져 있어(README 참고) 후보 목록 작성 시
# 수기로 대조한 이름을 그대로 재사용한다. 대시보드 검색창 표시용일 뿐 계산에는
# 안 쓰인다.
TICKER_NAMES: dict[str, str] = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "000270": "기아",
    "068270": "셀트리온", "005490": "POSCO홀딩스", "105560": "KB금융",
    "055550": "신한지주", "035420": "NAVER", "035720": "카카오",
    "012330": "현대모비스", "028260": "삼성물산", "066570": "LG전자",
    "051910": "LG화학", "006400": "삼성SDI", "015760": "한국전력",
    "032830": "삼성생명", "086790": "하나금융지주",
    "069500": "KODEX 200", "102110": "TIGER 200", "148020": "KBSTAR 200",
    "152100": "ARIRANG 200", "105190": "KINDEX 200", "069660": "KOSEF 200",
    "278530": "KODEX 200TR", "363580": "KODEX 200 IT TR", "091160": "KODEX 반도체",
    "091230": "TIGER 반도체", "091170": "KODEX 은행", "091180": "KODEX 자동차",
    "305720": "KODEX 2차전지산업", "229200": "KODEX 코스닥150", "244580": "KODEX 바이오",
}


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _issue_kis_token(creds) -> str | None:
    """KIS 토큰 발급 — 분당 1회 수준으로 제한되어 있어(반복적으로 걸린 이력
    있음) build_payload() 안에서 딱 한 번만 호출하고 여러 곳에서 공유한다."""
    try:
        token_resp = requests.post(
            f"{creds.base_url}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
            timeout=10,
        )
        token_resp.raise_for_status()
        return token_resp.json()["access_token"]
    except Exception:
        return None


def build_account_status(creds=None, token: str | None = None) -> dict:
    """실계좌 잔고(읽기 전용 조회) — KIS 장애·인증정보 없음·레이트리밋 등으로
    실패해도 대시보드 전체 생성은 막지 않도록 항상 dict를 반환한다.

    creds/token을 넘기면(예: build_payload()가 이미 발급한 토큰) 재발급 없이
    재사용한다 — build_index_strip()과 한 실행 안에서 토큰을 두 번 발급하면
    KIS 레이트리밋에 걸려 매번 둘 중 하나가 실패하는 문제가 실측으로 확인돼
    이 공유 방식으로 바꿨다."""
    if creds is None:
        try:
            creds = load_credentials()
        except CredentialsMissingError:
            return {"available": False, "error": "인증정보 없음"}

    try:
        if token is None:
            token = _issue_kis_token(creds)
        if token is None:
            return {"available": False, "error": "토큰 발급 실패"}

        resp = requests.get(
            f"{creds.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "appkey": creds.app_key,
                "appsecret": creds.app_secret,
                "tr_id": TR_ID_BALANCE[creds.env],
                "custtype": "P",
            },
            params={
                "CANO": creds.account_no, "ACNT_PRDT_CD": creds.account_product_cd,
                "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}"}

    if data.get("rt_cd") != "0":
        return {"available": False, "error": data.get("msg1", "조회 실패").strip()}

    summary = (data.get("output2") or [{}])[0]
    holdings = [
        {
            "ticker": h.get("pdno", ""),
            "name": h.get("prdt_name", ""),
            "qty": int(_to_float(h.get("hldg_qty"))),
            "avg_price": _to_float(h.get("pchs_avg_pric")),
            "cur_price": _to_float(h.get("prpr")),
            "eval_amount": _to_float(h.get("evlu_amt")),
            "pnl_pct": _to_float(h.get("evlu_pfls_rt")),
        }
        for h in data.get("output1", []) if int(_to_float(h.get("hldg_qty"))) > 0
    ]
    holdings.sort(key=lambda h: h["eval_amount"], reverse=True)

    return {
        "available": True,
        "env": creds.env,
        "deposit": _to_float(summary.get("dnca_tot_amt")),
        "stock_eval_amount": _to_float(summary.get("scts_evlu_amt")),
        "total_eval_amount": _to_float(summary.get("tot_evlu_amt")),
        "purchase_amount": _to_float(summary.get("pchs_amt_smtl_amt")),
        "pnl_amount": _to_float(summary.get("evlu_pfls_smtl_amt")),
        "pnl_rate": _to_float(summary.get("asst_icdc_erng_rt")),
        "holdings": holdings,
    }


TR_ID_INDEX_PRICE = "FHPUP02100000"   # 업종 현재지수(inquire-index-price)
INDEX_STRIP_SPARKLINE_LIMIT = 60   # 대시보드 페이로드 크기 억제용 — 스파크라인은 종가만 최근 60거래일


def build_index_strip(creds=None, token: str | None = None) -> dict:
    """B1 "지수 스트립" — 코스피/코스닥/코스피200 현재가+최근 스파크라인.

    스파크라인(최근 ~60거래일 종가)은 collect_index_bars.py가 채우는 로컬
    캐시(data/index_bars/*.jsonl)만 읽는다 — 라이브 호출 없이 항상 그릴 수
    있다. 현재가/등락률은 KIS inquire-index-price를 지수별로 조회한다.

    creds/token을 넘기면(build_payload()가 이미 발급한 토큰) 재발급하지
    않는다 — build_account_status()와 각자 토큰을 발급하면 같은 실행 안에서
    수 초 간격으로 두 번 발급하는 셈이라 KIS 레이트리밋(분당 1회 수준)에
    걸려 실제로 매번 둘 중 하나가 실패하는 것을 확인해(대시보드 정상 실행
    중 지수 3개 실시간 조회가 0/3으로 실패) 토큰을 공유하도록 고쳤다.
    인자를 안 넘기면 이 함수 스스로 발급한다(단독 호출·테스트 대비).

    토큰 발급 자체가 실패하거나(인증정보 없음/레이트리밋 등) 개별 지수
    조회가 실패해도 예외를 던지지 않는다 — 그 지수는 live_available=False로
    표시하고 캐시된 스파크라인만 보여준다(다른 build_*()들과 동일한
    "부분 실패가 전체를 막지 않는다" 계약).
    """
    if creds is None:
        try:
            creds = load_credentials()
        except CredentialsMissingError:
            creds = None

    if creds is not None and token is None:
        token = _issue_kis_token(creds)

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    indices_out = []
    for key, code in INDEX_CODES.items():
        bars = load_daily_bars(daily_store_path(INDEX_BARS_DIR, key))
        sparkline = [b.close for b in bars[-INDEX_STRIP_SPARKLINE_LIMIT:]]
        as_of = bars[-1].date if bars else None

        current = None
        change_pct = None
        live_available = False
        if token is not None:
            try:
                resp = requests.get(
                    f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-index-price",
                    headers={
                        "content-type": "application/json",
                        "authorization": f"Bearer {token}",
                        "appkey": creds.app_key,
                        "appsecret": creds.app_secret,
                        "tr_id": TR_ID_INDEX_PRICE,
                        "custtype": "P",
                    },
                    params={"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("rt_cd") != "0":
                    raise RuntimeError(data.get("msg1", "조회 실패").strip())
                output = data.get("output") or {}
                current = _to_float(output.get("bstp_nmix_prpr"))
                change_pct = _to_float(output.get("bstp_nmix_prdy_ctrt"))
                live_available = True
                as_of = now_iso
            except Exception:
                current = None
                change_pct = None
                live_available = False

        indices_out.append({
            "key": key,
            "label": INDEX_LABELS[key],
            "current": current,
            "change_pct": change_pct,
            "as_of": as_of,
            "sparkline_closes": sparkline,
            "live_available": live_available,
        })

    return {"indices": indices_out}


DAILY_BARS_EMBEDDED_LIMIT = 260   # 대시보드 페이로드 크기 억제용(약 1년치) — weekly/monthly는 전체 이력으로 계산 후 별도 임베드
EQUITY_CURVE_EMBEDDED_LIMIT = 730   # 대시보드 페이로드 크기 억제용(약 2년치 일별 스냅샷)


def build_equity_curve() -> dict:
    """실계좌 자산 곡선(B4) — account_snapshots.jsonl을 읽기만 하는 순수 함수.

    스냅샷 자체의 append는 main()에서 한다(이미 fetch한 payload["account"]를
    재사용하기 위해, 그리고 이 파일의 다른 build_*()들처럼 부작용 없는 순수
    읽기로 유지하기 위해 — 이 함수를 호출한다고 새 스냅샷이 쓰이지 않는다).
    """
    all_snapshots = load_snapshots(ACCOUNT_SNAPSHOTS_PATH)
    daily = latest_per_date(all_snapshots)
    limited = daily[-EQUITY_CURVE_EMBEDDED_LIMIT:]
    return {
        "points": [
            {"date": s.date, "total_eval_amount": s.total_eval_amount, "pnl_amount": s.pnl_amount}
            for s in limited
        ],
        "n_total_snapshots": len(all_snapshots),
    }


def _bar_dict(b: OhlcvBar) -> dict:
    # 키를 한 글자로 줄인다 — chart_catalog가 워치리스트 35종목 x 3개 타임프레임을
    # 통째로 임베드해 페이로드가 커서(README "대시보드가 무거워짐" 참고) 반복되는
    # 키 이름 자체가 용량을 크게 차지했다.
    return {"d": b.date, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}


def _minute_bar_dict(b) -> dict:
    return {"d": b.date, "t": b.time, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}


def build_chart_catalog(holdings: list[dict]) -> dict:
    """종목별 차트(분봉/일봉/주봉/월봉) 데이터.

    일봉은 워치리스트 캐시(data/daily_bars, collect_daily_bars_watchlist.py가
    하루 한 번 채움)를 읽기만 한다 — 매 대시보드 생성마다 pykrx를 라이브
    호출하지 않는다. 보유 종목인데 워치리스트에 없는 경우에만 예외적으로
    즉석 조회한다(보유종목 수가 적어 비용이 작다). 분봉은 보유종목에
    한해서만 키움 API로 매번 즉석 조회(사용자 선택) — 워치리스트 전체에
    분봉까지 매번 받으면 대시보드 생성이 느려지고 레이트리밋에 걸린다.
    """
    held_names = {h["ticker"]: h["name"] for h in holdings}
    all_tickers = list(dict.fromkeys(list(held_names.keys()) + WATCHLIST))

    kiwoom_creds = None
    kiwoom_token = None
    if held_names:
        try:
            kiwoom_creds = load_kiwoom_credentials()
            kiwoom_token = issue_kiwoom_token(kiwoom_creds)
        except Exception:
            kiwoom_creds = None

    catalog: dict[str, dict] = {}
    for ticker in all_tickers:
        daily = load_daily_bars(daily_store_path(DAILY_BARS_DIR, ticker))

        if not daily and ticker in held_names:
            try:
                end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
                start = (dt.date.today() - dt.timedelta(days=DAILY_LOOKBACK_DAYS_FOR_UNCACHED_HOLDING)).strftime("%Y%m%d")
                daily = fetch_ohlcv(ticker, start, end)
            except Exception:
                daily = []

        if not daily and ticker not in held_names:
            continue   # 워치리스트 캐시가 아직 없고 보유종목도 아니면 건너뜀(다음 일일수집 후 등장)

        minute = None
        if ticker in held_names and kiwoom_creds is not None:
            try:
                minute_bars = fetch_kiwoom_minute_bars(kiwoom_creds, kiwoom_token, ticker, MINUTE_MAX_CALLS_FOR_HELD)
                minute = [_minute_bar_dict(b) for b in minute_bars] if minute_bars else None
            except Exception:
                minute = None

        catalog[ticker] = {
            "name": held_names.get(ticker) or TICKER_NAMES.get(ticker, ticker),
            "daily": [_bar_dict(b) for b in daily[-DAILY_BARS_EMBEDDED_LIMIT:]],
            "weekly": [_bar_dict(b) for b in resample_weekly(daily)],
            "monthly": [_bar_dict(b) for b in resample_monthly(daily)],
            "minute": minute,
        }
    return catalog


def build_us_minute_bar_status() -> dict:
    """미국주식 5분봉 축적 현황(collect_minute_bars_us.py가 쌓는 데이터) 요약."""
    tickers = []
    if US_MINUTE_BARS_DIR.exists():
        for path in sorted(US_MINUTE_BARS_DIR.glob("*.jsonl")):
            bars = load_bars(path)
            if not bars:
                continue
            dates = sorted({b.date for b in bars})
            tickers.append({
                "ticker": path.stem,
                "bar_count": len(bars),
                "earliest_date": dates[0],
                "latest_date": dates[-1],
                "days_covered": len(dates),
            })
    heartbeat = (
        US_MINUTE_HEARTBEAT_PATH.read_text(encoding="utf-8").strip()
        if US_MINUTE_HEARTBEAT_PATH.exists() else None
    )
    return {"heartbeat": heartbeat, "tickers": tickers}


def _read_last_nonempty_line(path: Path, chunk_size: int = 8192) -> str | None:
    """파일 끝에서 청크 단위로만 읽어 마지막으로 비어있지 않은 줄을 얻는다.

    data/minute_bars_kiwoom/*.jsonl은 종목당 최대 수만 줄(5분봉 x 최대
    1년치)이라 build_us_minute_bar_status()처럼 load_bars()로 전체를
    파싱하면 이 상태 표 하나 만드는 데만 너무 느려진다 — 필요한 건
    "가장 최근 날짜" 하나뿐이므로 끝에서부터 몇 KB만 읽는다(줄바꿈이
    하나라도 나오면 그걸로 충분, 극단적으로 긴 한 줄짜리 파일이면 파일
    전체까지 확장해서 읽는다).
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None
    with path.open("rb") as f:
        data = b""
        pos = size
        while True:
            step = min(chunk_size, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
            if data.rstrip(b"\n").count(b"\n") >= 1 or pos == 0:
                break
    stripped = data.rstrip(b"\n")
    last_line = stripped.rsplit(b"\n", 1)[-1]
    text = last_line.decode("utf-8", errors="replace").strip()
    return text or None


def _latest_date_in_file(path: Path) -> str | None:
    line = _read_last_nonempty_line(path)
    if not line:
        return None
    try:
        return json.loads(line).get("date")
    except (json.JSONDecodeError, AttributeError):
        return None


def _pipeline_health(key: str, label: str, dir_path: Path, heartbeat_path: Path) -> dict:
    """파이프라인 하나의 요약 상태(B6) — 원본 데이터는 절대 담지 않고
    집계된 개수/날짜/용량만 담는다. Path.stat()과 각 파일의 마지막 줄만
    읽어(전체 파싱 없이) minute_bars_kiwoom처럼 큰 디렉터리에서도 빠르다.
    디렉터리가 아직 없으면 에러 대신 "미가동"으로 보고한다.
    """
    if not dir_path.exists():
        return {
            "key": key, "label": label, "available": False,
            "heartbeat": None, "heartbeat_age_hours": None, "is_stale": True,
            "file_count": 0, "latest_date": None, "dir_size_bytes": 0,
        }

    files = sorted(dir_path.glob("*.jsonl"))
    latest_date = None
    for f in files:
        d = _latest_date_in_file(f)
        if d and (latest_date is None or d > latest_date):
            latest_date = d

    dir_size_bytes = sum(f.stat().st_size for f in dir_path.glob("*") if f.is_file())

    heartbeat = None
    heartbeat_age_hours = None
    if heartbeat_path.exists():
        raw = heartbeat_path.read_text(encoding="utf-8").strip()
        try:
            heartbeat_age_hours = (dt.datetime.now() - dt.datetime.fromisoformat(raw)).total_seconds() / 3600
            heartbeat = raw
        except ValueError:
            heartbeat = None   # 하트비트 파일이 있어도 파싱 안 되면 "없음"과 동일 취급

    is_stale = heartbeat_age_hours is None or heartbeat_age_hours > STALE_HOURS_THRESHOLD

    return {
        "key": key, "label": label, "available": True,
        "heartbeat": heartbeat, "heartbeat_age_hours": heartbeat_age_hours,
        "is_stale": is_stale, "file_count": len(files),
        "latest_date": latest_date, "dir_size_bytes": dir_size_bytes,
    }


def build_system_health() -> dict:
    """B6: 데이터·시스템 상태 — 가짜 CPU/RAM 게이지 대신 실측 가능한 것만.

    파이프라인별 하트비트 나이·축적 파일 수·최신 날짜·용량을 집계한다.
    generation_timing은 여기서 채우지 않는다 — 이 함수 자신의 실행시간은
    스스로 잴 수 없으므로(다른 build_*()들처럼 부작용 없는 순수 함수로
    유지하기 위해) main()이 build_payload() 전체를 감싸 잰 뒤 주입한다.
    """
    return {"pipelines": [_pipeline_health(**p) for p in SYSTEM_HEALTH_PIPELINES]}


def build_strategy_data() -> dict:
    """전략별 페이퍼 트레이딩 현황(읽기전용) + 손익달력용 통합 거래 목록.

    사전등록 파라미터는 config_note로 echo만 한다(재선택 없음). 서킷브레이커
    상태는 CircuitBreakerConfig 기본값 대비 진행률로 표시 — 실제 halt 판정은
    각 페이퍼 트레이딩 스크립트가 진입 시점에 이미 수행한다, 여기서는 표시만.
    """
    cb_config = CircuitBreakerConfig()
    strategies_out = []
    all_resolved: list[dict] = []

    for s in STRATEGIES:
        entries = load_entries(s["log_path"])
        resolved = [e for e in entries if e.is_resolved]
        pending = [e for e in entries if not e.is_resolved]
        wins = [e for e in resolved if e.pnl_pct is not None and e.pnl_pct > 0]
        win_rate = (len(wins) / len(resolved) * 100) if resolved else None
        cum_pnl_pct = sum(e.pnl_pct for e in resolved) * 100 if resolved else 0.0

        strategies_out.append({
            "key": s["key"], "label": s["label"], "config_note": s["config_note"],
            "n_resolved": len(resolved), "n_pending": len(pending),
            "win_rate": win_rate, "cum_pnl_pct": cum_pnl_pct,
            "consecutive_losses": consecutive_losses(entries),
            "consecutive_losses_limit": cb_config.max_consecutive_losses,
            "current_drawdown_pct": current_drawdown(entries) * 100,
            "drawdown_limit_pct": cb_config.max_drawdown_pct * 100,
        })
        for e in resolved:
            all_resolved.append({
                "strategy": s["key"], "ticker": e.ticker, "date": e.date,
                "entry_price": e.entry_price, "target_price": e.target_price,
                "stop_price": e.stop_price, "resolution": e.resolution,
                "pnl_pct": e.pnl_pct * 100,
            })

    return {"strategies": strategies_out, "resolved_trades": all_resolved}


def build_risk_metrics() -> dict:
    """두 전략(KR/ETF) 통합 위험지표 — Sharpe/Sortino/VaR는 표본 부족 시 None.

    cluster_bootstrap.moving_block_bootstrap은 daily_records 길이가
    block_length(15) 미만이면 ValueError를 던진다 — 표본부족을 그대로
    실패로 전파하지 않고 여기서 흡수해 "부트스트랩 미가동"으로 표시한다.
    """
    combined_entries = [
        e for s in STRATEGIES for e in load_entries(s["log_path"]) if e.is_resolved
    ]
    series = daily_pnl_series(combined_entries)
    daily_returns = [r for _, r in series]
    n_days = len(daily_returns)

    bootstrap_ci = None
    try:
        by_date: dict[str, list[float]] = {}
        for e in combined_entries:
            by_date.setdefault(e.date, []).append(e.pnl_pct)
        records = [
            DailyRecord(date=d, account_return=sum(v) / len(v),
                        trades=[{"pnl_pct": p, "is_win": p > 0} for p in v])
            for d, v in sorted(by_date.items())
        ]
        result = moving_block_bootstrap(records, block_length=15, n_resamples=1000)
        lo, hi = result.ci("account_metrics", "mdd")
        bootstrap_ci = {"mdd_ci_low_pct": lo * 100, "mdd_ci_high_pct": hi * 100}
    except ValueError:
        bootstrap_ci = None

    return {
        "n_trading_days": n_days,
        "n_trades": len(combined_entries),
        "sharpe": sharpe_ratio(daily_returns),
        "sortino": sortino_ratio(daily_returns),
        "var95_pct": (v * 100 if (v := historical_var(daily_returns, 0.95)) is not None else None),
        "max_drawdown_pct": current_drawdown(combined_entries) * 100 if combined_entries else 0.0,
        "min_days_for_ratio": MIN_DAYS_FOR_RATIO,
        "min_days_for_var": MIN_DAYS_FOR_VAR,
        "bootstrap_ci": bootstrap_ci,
    }


ALERTS_EMBEDDED_LIMIT = 50   # 대시보드 페이로드 크기 억제용(chart_catalog 교훈 — README "대시보드가 무거워짐" 참고)


def _state_summary(payload: dict) -> dict:
    """diff_states()의 입력이 될 축약 상태 dict — payload 전체가 아니라
    "상태전환 감지"에 필요한 최소 필드만 뽑는다(순수 함수, I/O 없음).
    """
    return {
        "halt_status": payload["halt_status"],
        "pipelines": {
            p["key"]: {"is_stale": p["is_stale"], "available": p["available"], "label": p["label"]}
            for p in payload["system_health"]["pipelines"]
        },
        "account_available": payload["account"]["available"],
        "strategies": {
            s["key"]: {"n_resolved": s["n_resolved"], "label": s["label"]}
            for s in payload["strategy_data"]["strategies"]
        },
    }


def build_alerts() -> dict:
    """alerts.jsonl을 읽기만 하는 순수 함수(B5) — 새 알림 판정·append는 main()의 몫.

    다른 build_*()들처럼 부작용 없는 읽기 전용 — 이 함수를 호출한다고 새
    알림이 쌓이지 않는다(equity_curve와 동일한 "읽기/쓰기 분리" 패턴).
    """
    all_alerts = load_alerts(ALERTS_LOG_PATH)
    capped = all_alerts[-ALERTS_EMBEDDED_LIMIT:]
    return {
        "alerts": [asdict(a) for a in capped],
        "n_total": len(all_alerts),
    }


def build_backtest_results() -> dict:
    """B7: 사전 등록 백테스트 결과 탭 — phase0/backtest/preregistered_results.py의
    고정 상수를 JSON 직렬화 가능한 구조로 재배열만 한다(계산 없음, 순수 읽기).

    이 함수가 실행할 때마다 새로 계산하는 값은 하나도 없다 — README.md에
    이미 보고된 사전 등록 격자 백테스트 결과를 그대로 옮겨 적은 정적 데이터를
    반환할 뿐이다(재실행/재계산 버튼이 없는 이유와 동일한 원칙).
    """
    return {
        "result_sets": [
            {
                "key": rs.key,
                "title": rs.title,
                "strategy": rs.strategy,
                "universe": rs.universe,
                "period": rs.period,
                "columns": list(rs.columns),
                "rows": [
                    {
                        "cells": list(row.cells),
                        "verdict": row.verdict,
                        "verdict_detail": row.verdict_detail,
                        "best": row.best,
                    }
                    for row in rs.rows
                ],
                "conclusion": rs.conclusion,
                "source": rs.source,
                "date": rs.date,
                "incomplete_note": rs.incomplete_note,
            }
            for rs in ALL_RESULT_SETS
        ],
    }


def build_signal_breakdown(holdings: list[dict]) -> dict:
    """B3 "시그널" 탭: 워치리스트(+보유) 종목별 GDR 조건(C1~C5) 분해.

    **회고적**이다 — 가장 최근 수집된 일봉을 "오늘"로 간주해, 그 시가에서 GDR이
    무엇이라 판정했을지를 evaluate_conditions()로 재현한다(장중 실시간 신호 아님).
    build_chart_catalog와 동일하게 워치리스트 일봉 캐시만 읽고(라이브 호출 없음),
    보유종목을 앞에 합쳐 종목 집합을 정한다.

    페이로드에는 **스칼라만** 담는다 — 평가에 쓴 봉 이력은 절대 포함하지 않는다
    (chart_catalog에 이미 있으므로 중복 임베드 금지, README "대시보드가 무거워짐").
    """
    held_names = {h["ticker"]: h["name"] for h in holdings}
    all_tickers = list(dict.fromkeys(list(held_names.keys()) + WATCHLIST))

    tickers_out = []
    for ticker in all_tickers:
        bars = load_daily_bars(daily_store_path(DAILY_BARS_DIR, ticker))
        # '오늘' 봉 하나를 떼어내 history로 평가하려면 최소 MIN_HISTORY+1개 필요.
        if len(bars) < MIN_HISTORY + 1:
            continue
        history = bars[:-1]
        today = bars[-1]
        report = evaluate_conditions(history, today.open, today.date)

        # 표시용 페이로드라 프랙션 값은 6자리로 반올림해 용량을 줄인다(UI는
        # 소수 2자리 %까지만 보여준다 — chart_catalog "짧은 키" 교훈의 연장선).
        def _r(v, n):
            return round(v, n) if v is not None else None

        tickers_out.append({
            "ticker": ticker,
            "name": held_names.get(ticker) or TICKER_NAMES.get(ticker, ticker),
            "date": today.date,
            "d1_close": _r(history[-1].close, 2),   # C1 표시용(y.close, 평가에 쓰인 D-1 종가)
            "insufficient_history": report.insufficient_history,
            "passed_all": report.passed_all,
            "gap_pct": _r(report.gap_pct, 6),
            "atr_pct": _r(report.atr_pct, 6),
            "sma20": _r(report.sma20, 2),
            "gap_floor": _r(report.gap_floor, 6),
            "prev_day_return": _r(report.prev_day_return, 6),
            "c1_trend_ok": report.c1_trend_ok,
            "c2_gap_band_ok": report.c2_gap_band_ok,
            "c3_no_prior_crash_ok": report.c3_no_prior_crash_ok,
            "c4_volatility_band_ok": report.c4_volatility_band_ok,
            "c5_not_ex_div_window_ok": report.c5_not_ex_div_window_ok,
        })

    # 조건 기준선을 상수로 echo만 한다(단일 진실 공급원 = gap_rebound.py). UI가
    # "기준 밴드"를 표시할 때 템플릿에 숫자를 하드코딩하지 않도록.
    return {
        "tickers": tickers_out,
        "thresholds": {
            "trend_floor": TREND_FLOOR,
            "gap_cap": GAP_CAP,
            "prev_day_crash": PREV_DAY_CRASH,
            "atr_band_low": ATR_BAND[0],
            "atr_band_high": ATR_BAND[1],
            "min_history": MIN_HISTORY,
        },
    }


def build_payload() -> dict:
    entries = load_entries(LOG_PATH)
    today = dt.date.today().strftime("%Y%m%d")

    resolved = sorted([e for e in entries if e.is_resolved], key=lambda x: x.date)
    pending = [e for e in entries if not e.is_resolved]

    wins = [e for e in resolved if e.pnl_pct is not None and e.pnl_pct > 0]
    win_rate = (len(wins) / len(resolved) * 100) if resolved else None

    cum = 0.0
    cum_series = []
    for e in resolved:
        cum += e.pnl_pct
        cum_series.append({
            "date": e.date, "ticker": e.ticker,
            "cum_pnl_pct": cum * 100, "pnl_pct": e.pnl_pct * 100,
        })

    halt = check_halt(
        daily_return=daily_return(entries, today),
        weekly_return=weekly_return(entries, today),
        monthly_return=monthly_return(entries, today),
        consecutive_losses=consecutive_losses(entries),
        hours_since_market_crash=None,
        current_drawdown_pct=current_drawdown(entries),
        config=CircuitBreakerConfig(),
    )

    heartbeat = HEARTBEAT_PATH.read_text(encoding="utf-8").strip() if HEARTBEAT_PATH.exists() else None

    # KIS 토큰을 여기서 딱 한 번만 발급해 build_account_status()/build_index_strip()가
    # 공유한다 — 각자 발급하면 같은 실행 안에서 수 초 간격으로 두 번 발급하는
    # 셈이라 KIS 레이트리밋(분당 1회 수준)에 걸려 실제로 매번 둘 중 하나가
    # 실패하는 것을 실측으로 확인했다.
    kis_creds = None
    kis_token = None
    try:
        kis_creds = load_credentials()
    except CredentialsMissingError:
        kis_creds = None
    if kis_creds is not None:
        kis_token = _issue_kis_token(kis_creds)

    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "heartbeat": heartbeat,
        "halt_status": halt.value,
        "total_trades": len(resolved),
        "pending_count": len(pending),
        "win_rate": win_rate,
        "cum_pnl_pct": cum * 100,
        "consecutive_losses": consecutive_losses(entries),
        "cum_series": cum_series,
        "pending": [
            {"ticker": e.ticker, "date": e.date, "entry_price": e.entry_price,
             "target_price": e.target_price, "stop_price": e.stop_price, "shares": e.shares}
            for e in pending
        ],
        "history": [
            {"ticker": e.ticker, "date": e.date, "entry_price": e.entry_price,
             "target_price": e.target_price, "stop_price": e.stop_price, "shares": e.shares,
             "resolution": e.resolution,
             "pnl_pct": (e.pnl_pct * 100 if e.pnl_pct is not None else None)}
            for e in sorted(resolved, key=lambda x: x.date, reverse=True)
        ],
        "us_minute_bars": build_us_minute_bar_status(),
        "system_health": build_system_health(),
        "account": (account := build_account_status(kis_creds, kis_token)),
        "chart_catalog": build_chart_catalog(account["holdings"] if account["available"] else []),
        "signal_breakdown": build_signal_breakdown(account["holdings"] if account["available"] else []),
        "strategy_data": build_strategy_data(),
        "risk_metrics": build_risk_metrics(),
        "equity_curve": build_equity_curve(),
        "alerts": build_alerts(),
        "backtest_results": build_backtest_results(),
        "index_strip": build_index_strip(kis_creds, kis_token),
    }


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_PATH
    t0 = time.perf_counter()
    payload = build_payload()
    # build_system_health()는 다른 build_*()들처럼 부작용 없는 순수 함수로
    # 유지한다 — 자기 자신의 실행시간을 스스로 잴 수 없으므로, 전체
    # build_payload() 호출을 감싸 잰 뒤 여기서 주입한다(B6 "최근 생성
    # 소요시간" 표시용).
    payload["system_health"]["generation_timing"] = {
        "total_seconds": round(time.perf_counter() - t0, 3),
    }

    # 자산 곡선(B4) 스냅샷 append — payload["account"]는 build_payload() 안에서
    # build_account_status()로 이미 한 번 조회한 값이라 여기서 KIS를 다시
    # 호출하지 않는다(레이트리밋 이슈 반복 이력 있음). 조회 실패 시(available
    # False) 스냅샷을 남기지 않는다 — 0원이 아니라 "모름"이므로 곡선에 거짓
    # 데이터 포인트를 넣지 않기 위함.
    acct_for_snapshot = payload["account"]
    if acct_for_snapshot["available"]:
        today = dt.date.today().strftime("%Y%m%d")
        append_snapshot(ACCOUNT_SNAPSHOTS_PATH, AccountSnapshot(
            ts=dt.datetime.now().isoformat(timespec="seconds"),
            date=today,
            deposit=acct_for_snapshot["deposit"],
            stock_eval_amount=acct_for_snapshot["stock_eval_amount"],
            total_eval_amount=acct_for_snapshot["total_eval_amount"],
            pnl_amount=acct_for_snapshot["pnl_amount"],
        ))
        # build_payload() 안에서 계산된 equity_curve는 방금 append한 이
        # 스냅샷을 아직 반영하지 못한 상태(append가 그 이후에 일어났으므로)
        # — 다음 생성까지 기다리지 않고 이번 회차 대시보드에 바로 반영되도록
        # 다시 계산한다. build_equity_curve()는 순수 읽기라 재호출 비용이
        # 거의 없다(KIS 재호출과 달리 로컬 파일 읽기일 뿐).
        payload["equity_curve"] = build_equity_curve()

    # B5 알림: 직전 실행 상태(dashboard_state.json) 대비 상태전환만 사실로
    # 기록한다 — 파라미터·전략 변경 추천은 diff_states()가 절대 만들지
    # 않는다(house norm). 상태 파일이 아직 없으면(첫 실행) prev={}이고
    # diff_states()가 빈 목록을 반환해 알림 홍수를 막는다.
    prev_state = (
        json.loads(DASHBOARD_STATE_PATH.read_text(encoding="utf-8"))
        if DASHBOARD_STATE_PATH.exists() else {}
    )
    curr_state = _state_summary(payload)
    new_alerts = diff_states(prev_state, curr_state)
    for a in new_alerts:
        append_alert(ALERTS_LOG_PATH, a)
    DASHBOARD_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_STATE_PATH.write_text(json.dumps(curr_state, ensure_ascii=False), encoding="utf-8")
    if new_alerts:
        # build_payload() 안에서 계산된 payload["alerts"]는 방금 append한
        # 알림들을 아직 반영하지 못한 상태 — equity_curve와 동일한 이유로
        # 다시 계산해 이번 회차 대시보드에 바로 반영한다.
        payload["alerts"] = build_alerts()

    payload_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__PAYLOAD_JSON__", payload_json)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"대시보드 생성 완료: {out_path}")
    print(f"  총 거래(해소): {payload['total_trades']}, 진행중: {payload['pending_count']}, "
          f"서킷브레이커: {payload['halt_status']}")
    print(f"  미국 분봉 추적 종목: {len(payload['us_minute_bars']['tickers'])}개")
    acct = payload["account"]
    if acct["available"]:
        print(f"  실계좌({acct['env']}): 총평가금액 {acct['total_eval_amount']:,.0f}원, "
              f"보유종목 {len(acct['holdings'])}건")
    else:
        print(f"  실계좌 조회 실패: {acct['error']}")
    print(f"  종목별 차트 캐시: {len(payload['chart_catalog'])}종목")
    sb = payload["signal_breakdown"]
    n_pass = sum(1 for t in sb["tickers"] if t["passed_all"])
    print(f"  시그널 분해(회고적): {len(sb['tickers'])}종목 평가, 조건 전부 통과 {n_pass}종목")
    rm = payload["risk_metrics"]
    print(f"  위험지표: 거래일수={rm['n_trading_days']}, sharpe={rm['sharpe']}, "
          f"sortino={rm['sortino']}, VaR95={rm['var95_pct']}")
    ec = payload["equity_curve"]
    print(f"  자산 곡선: 일별 스냅샷 {len(ec['points'])}건(전체 누적 {ec['n_total_snapshots']}건)")
    sh = payload["system_health"]
    n_available = sum(1 for p in sh["pipelines"] if p["available"])
    n_stale = sum(1 for p in sh["pipelines"] if p["available"] and p["is_stale"])
    print(f"  시스템 상태: 파이프라인 {len(sh['pipelines'])}개 중 가동 {n_available}개"
          f"(지연 {n_stale}개), 생성 소요시간 {sh['generation_timing']['total_seconds']:.2f}초")
    print(f"  알림: 이번 실행 신규 {len(new_alerts)}건, 누적 {payload['alerts']['n_total']}건")
    print(f"  백테스트 결과 탭: 결과셋 {len(payload['backtest_results']['result_sets'])}개(정적 데이터, README 전사)")
    idx = payload["index_strip"]["indices"]
    n_live = sum(1 for i in idx if i["live_available"])
    bars_str = ", ".join(f"{i['label']}={len(i['sparkline_closes'])}봉" for i in idx)
    print(f"  지수 스트립: {len(idx)}개 중 실시간 조회 성공 {n_live}개 ({bars_str})")


if __name__ == "__main__":
    main()
