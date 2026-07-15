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
from pathlib import Path

_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    # 이 스크립트를 `python scripts/generate_dashboard.py`로 직접 실행하면
    # sys.path[0]이 scripts/ 자신이라 형제 스크립트(collect_*)를
    # "scripts.X"로 임포트할 수 없다(pytest는 rootdir를 자동으로 넣어주지만
    # 직접 실행은 아니다) — 그래서 저장소 루트를 명시적으로 추가한다.
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))

import requests

from phase0.bootstrap.cluster_bootstrap import DailyRecord, moving_block_bootstrap
from phase0.config.kis_credentials import CredentialsMissingError, load_credentials
from phase0.config.kiwoom_credentials import load_credentials as load_kiwoom_credentials
from phase0.data.bar_resample import resample_monthly, resample_weekly
from phase0.data.daily_bar_store import load_bars as load_daily_bars, store_path as daily_store_path
from phase0.data.minute_bar_store import load_bars
from phase0.data.pykrx_ingest import OhlcvBar, fetch_ohlcv
from phase0.paper.trade_log import (
    consecutive_losses, current_drawdown, daily_return, load_entries, monthly_return,
    weekly_return,
)
from phase0.risk.circuit_breaker import CircuitBreakerConfig, check_halt
from phase0.risk.metrics import (
    MIN_DAYS_FOR_RATIO, MIN_DAYS_FOR_VAR, daily_pnl_series, historical_var, sharpe_ratio,
    sortino_ratio,
)
from scripts.collect_daily_bars_watchlist import BASE_DIR as DAILY_BARS_DIR, WATCHLIST
from scripts.collect_minute_bars_kiwoom import fetch_ticker_bars as fetch_kiwoom_minute_bars, issue_token as issue_kiwoom_token

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "paper_trading" / "gdr_trades.jsonl"
HEARTBEAT_PATH = REPO_ROOT / "data" / "paper_trading" / "heartbeat.txt"
ETF_LOG_PATH = REPO_ROOT / "data" / "paper_trading_etf" / "gdr_trades.jsonl"
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


def build_account_status() -> dict:
    """실계좌 잔고(읽기 전용 조회) — KIS 장애·인증정보 없음·레이트리밋 등으로
    실패해도 대시보드 전체 생성은 막지 않도록 항상 dict를 반환한다."""
    try:
        creds = load_credentials()
    except CredentialsMissingError:
        return {"available": False, "error": "인증정보 없음"}

    try:
        token_resp = requests.post(
            f"{creds.base_url}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
            timeout=10,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]

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


DAILY_BARS_EMBEDDED_LIMIT = 260   # 대시보드 페이로드 크기 억제용(약 1년치) — weekly/monthly는 전체 이력으로 계산 후 별도 임베드


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
        "account": (account := build_account_status()),
        "chart_catalog": build_chart_catalog(account["holdings"] if account["available"] else []),
        "strategy_data": build_strategy_data(),
        "risk_metrics": build_risk_metrics(),
    }


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_PATH
    payload = build_payload()
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
    rm = payload["risk_metrics"]
    print(f"  위험지표: 거래일수={rm['n_trading_days']}, sharpe={rm['sharpe']}, "
          f"sortino={rm['sortino']}, VaR95={rm['var95_pct']}")


if __name__ == "__main__":
    main()
