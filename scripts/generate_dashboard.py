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

import requests

from phase0.config.kis_credentials import CredentialsMissingError, load_credentials
from phase0.data.minute_bar_store import load_bars
from phase0.paper.trade_log import (
    consecutive_losses, current_drawdown, daily_return, load_entries, monthly_return,
    weekly_return,
)
from phase0.risk.circuit_breaker import CircuitBreakerConfig, check_halt

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "paper_trading" / "gdr_trades.jsonl"
HEARTBEAT_PATH = REPO_ROOT / "data" / "paper_trading" / "heartbeat.txt"
TEMPLATE_PATH = REPO_ROOT / "scripts" / "dashboard_template.html"
DEFAULT_OUT_PATH = REPO_ROOT / "data" / "paper_trading" / "dashboard.html"

US_MINUTE_BARS_DIR = REPO_ROOT / "data" / "minute_bars_us"
US_MINUTE_HEARTBEAT_PATH = US_MINUTE_BARS_DIR / "heartbeat.txt"

TR_ID_BALANCE = {"prod": "TTTC8434R", "vps": "VTTC8434R"}


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
        "account": build_account_status(),
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


if __name__ == "__main__":
    main()
