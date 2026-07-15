#!/usr/bin/env python3
"""GDR ETF 페이퍼 트레이딩 — 실주문 없이 신호·가상 체결만 기록 (2026-07-16).

배경: 개별주식 GDR(scripts/paper_trade_gdr.py)과 완전히 같은 구조이지만
대상이 국내 주식형 ETF다 — ETF는 거래세·농특세가 전액 면제돼(README
"논점 전환: ETF 비용구조") Base 비용이 개별주식(0.3854%)의 절반
수준(0.1854%)이고, 59종목 백테스트에서 GDR이 개별주식보다 뚜렷이
0에 가까운 결과(−0.11%)를 냈다 — 그 다음 단계로 진짜 새 데이터(페이퍼
트레이딩)를 쌓기 시작한다.

라벨/파라미터는 ETF 격자 실험에서 이미 확정된 챔피언(f_fill=1.0,
k_stop=1.0)을 그대로 승계 — 결과를 보고 다시 고르지 않는다. 데이터
수집(pykrx get_market_ohlcv)·시세 조회(KIS)·서킷브레이커·포지션
사이징은 개별주식 GDR과 동일 코드를 그대로 재사용한다 — 시장이
다를 뿐 로직은 공통이라는 이 프로젝트의 일관된 설계 원칙.

로그 위치: data/paper_trading_etf/gdr_trades.jsonl (개별주식 로그와
분리, gitignore 처리).

사용법: python scripts/paper_trade_etf_gdr.py --mode entry|resolve [--universe default|expanded]
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import requests

from phase0.backtest.g0_backtester import DailyBar, Signal, resolve_trade
from phase0.config.kis_credentials import CredentialsMissingError, load_credentials
from phase0.data.etf_candidates import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.pykrx_ingest import fetch_ohlcv
from phase0.engine.position_sizing import size_by_risk
from phase0.paper.trade_log import (
    PaperEntry, append_entry, consecutive_losses, current_drawdown, daily_return,
    load_entries, monthly_return, rewrite_all, weekly_return,
)
from phase0.risk.circuit_breaker import CircuitBreakerConfig, HaltReason, check_halt
from phase0.strategy.gap_rebound import gap_rebound_signal

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}

F_FILL, K_STOP = 1.0, 1.0            # 59종목 ETF 격자 실험에서 확정된 챔피언 승계
PAPER_CAPITAL_KRW = 10_000_000.0     # 페이퍼 트레이딩 가정 자본 — 실제 자본과 무관한 플레이스홀더
HISTORY_LOOKBACK_DAYS = 60           # GDR MIN_HISTORY(22봉) 확보용 여유

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "paper_trading_etf" / "gdr_trades.jsonl"
HEARTBEAT_PATH = REPO_ROOT / "data" / "paper_trading_etf" / "heartbeat.txt"

TR_ID_INQUIRE_PRICE = "FHKST01010100"  # 주식현재가 시세 (ETF도 동일 TR — 실측 확인)


def write_heartbeat() -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(dt.datetime.now().isoformat(), encoding="utf-8")


def issue_access_token(creds) -> str:
    resp = requests.post(
        f"{creds.base_url}/oauth2/tokenP",
        headers={"content-type": "application/json"},
        json={"grant_type": "client_credentials", "appkey": creds.app_key, "appsecret": creds.app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_quote(creds, token: str, ticker: str) -> dict:
    resp = requests.get(
        f"{creds.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": creds.app_key,
            "appsecret": creds.app_secret,
            "tr_id": TR_ID_INQUIRE_PRICE,
        },
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("output", {})


def circuit_breaker_status(entries: list[PaperEntry], today: str) -> HaltReason:
    return check_halt(
        daily_return=daily_return(entries, today),
        weekly_return=weekly_return(entries, today),
        monthly_return=monthly_return(entries, today),
        consecutive_losses=consecutive_losses(entries),
        hours_since_market_crash=None,   # 시장 급락 감지는 별도 배선 필요 — 아직 없음
        current_drawdown_pct=current_drawdown(entries),
        config=CircuitBreakerConfig(),
    )


def run_entry(tickers: list[str]) -> None:
    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    today = dt.date.today().strftime("%Y%m%d")
    entries = load_entries(LOG_PATH)

    halt = circuit_breaker_status(entries, today)
    if halt != HaltReason.NONE:
        print(f"서킷브레이커 발동: {halt.value} — 오늘 신규 진입을 건너뜁니다.")
        write_heartbeat()
        return

    token = issue_access_token(creds)
    start = (dt.date.today() - dt.timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")   # D-1까지만 — 룩어헤드 없음

    n_signals = 0
    for ticker in tickers:
        try:
            history = fetch_ohlcv(ticker, start, end)
        except Exception as exc:
            print(f"  {ticker}: 이력 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        if len(history) < 22:
            continue

        try:
            quote = fetch_quote(creds, token, ticker)
            today_open = float(quote["stck_oprc"])
        except (KeyError, ValueError, requests.RequestException) as exc:
            print(f"  {ticker}: 시세 조회 실패 ({type(exc).__name__}: {exc})")
            continue
        if today_open <= 0:
            continue

        sig = gap_rebound_signal(history, today_open, today, f_fill=F_FILL, k_stop=K_STOP)
        if sig is None:
            continue

        size = size_by_risk(PAPER_CAPITAL_KRW, sig)
        if size.shares <= 0:
            print(f"  {ticker}: 신호 발생했으나 리스크 예산 대비 1주도 못 삼 — 건너뜀")
            continue

        append_entry(LOG_PATH, PaperEntry(
            ticker=ticker, date=today, entry_price=sig.entry_price,
            target_price=sig.target_price, stop_price=sig.stop_price, shares=size.shares,
        ))
        n_signals += 1
        print(f"  {ticker}: 페이퍼 진입 기록 (시가={sig.entry_price:.0f}, "
              f"목표={sig.target_price:.0f}, 손절={sig.stop_price:.0f}, {size.shares}주)")

    print(f"\n{today} 페이퍼 진입 {n_signals}건 기록됨 (로그: {LOG_PATH})")
    write_heartbeat()


def run_resolve() -> None:
    try:
        creds = load_credentials()
    except CredentialsMissingError as exc:
        print(f"인증정보 없음: {exc}")
        return

    today = dt.date.today().strftime("%Y%m%d")
    entries = load_entries(LOG_PATH)
    pending = [e for e in entries if not e.is_resolved and e.date == today]

    if not pending:
        print(f"{today} 미결 페이퍼 진입 없음 — 해소할 게 없습니다.")
        write_heartbeat()
        return

    token = issue_access_token(creds)
    n_resolved = 0
    for entry in pending:
        try:
            quote = fetch_quote(creds, token, entry.ticker)
            bar = DailyBar(
                date=entry.date,
                open=float(quote["stck_oprc"]),
                high=float(quote["stck_hgpr"]),
                low=float(quote["stck_lwpr"]),
                close=float(quote["stck_prpr"]),
            )
        except (KeyError, ValueError, requests.RequestException) as exc:
            print(f"  {entry.ticker}: 시세 조회 실패, 해소 보류 ({type(exc).__name__}: {exc})")
            continue

        sig = Signal(date=entry.date, entry_price=entry.entry_price,
                     target_price=entry.target_price, stop_price=entry.stop_price)
        trade = resolve_trade(bar, sig, "conservative")
        entry.resolution = trade.resolution.value
        entry.pnl_pct = trade.pnl_pct
        n_resolved += 1
        print(f"  {entry.ticker}: {trade.resolution.value} (pnl={trade.pnl_pct * 100:+.3f}%)")

    rewrite_all(LOG_PATH, entries)
    print(f"\n{today} 페이퍼 진입 {n_resolved}건 해소 완료 (로그: {LOG_PATH})")
    write_heartbeat()


def main() -> None:
    args = sys.argv[1:]
    mode = None
    universe = "expanded"
    for i, a in enumerate(args):
        if a == "--mode":
            mode = args[i + 1]
        if a == "--universe":
            universe = args[i + 1]

    if mode == "entry":
        run_entry(UNIVERSES[universe])
    elif mode == "resolve":
        run_resolve()
    else:
        print("사용법: python scripts/paper_trade_etf_gdr.py --mode entry|resolve [--universe default|expanded]")


if __name__ == "__main__":
    main()
