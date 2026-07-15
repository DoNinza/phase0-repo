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


if __name__ == "__main__":
    main()
