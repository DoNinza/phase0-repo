"""Phase 1 게이트 (a) 실측 — EXPANDED_CANDIDATES 95종목 전수 소급·결측 확인.

docs/foreign_flow_nat_전략_기획안.md §8 Phase 1 항목 4의 사전 선언
게이트 중 (a)·(b)만 다룬다(게이트 (c) 공표 시점 실측은 별도 — 휴장일에는
의미가 없어 거래일에 따로 실행한다):

    (a) 95종목 중 수급 시계열 확보 ≥ 90종목 × 2016-07 소급
    (b) 결측일 비율 ≤ 5%(거래정지 등 정당 결측 제외)

`scripts/spike_investor_flow.py`(게이트 0, 표본 8종목)가 이미 로그인
자체가 뚫린다는 것을 확인했으므로, 이 스크립트는 그 확인을
EXPANDED_CANDIDATES 95종목 전체로 확장한다. 게이트 0 스파이크에서
LG에너지솔루션(373220)·삼성바이오로직스(207940)가 "2016-07 소급 실패"로
잡혔지만 실제로는 상장일이 그 이후라 데이터가 없는 게 정상이었던 것과
같은 구분을 95종목 전체에 자동으로 적용한다 — 소급이 실패한 종목마다
로그인이 필요 없는 `get_market_ohlcv`로 상장일 전후를 대조해 "진짜 데이터
문제"와 "상장일 때문에 정상적으로 없는 것"을 구분한다.

사용법:
    python scripts/spike_investor_flow_full.py

산출물(전부 .gitignore 처리된 data/investor_flow_spike/ 아래):
    full_spike_report.json — 종목별 상세(소급/상장일 확인/최근 결측) 전체
    gate_ab_report.json    — 게이트 (a)/(b) 최종 판정
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from phase0.config.krx_credentials import CredentialsMissingError, ensure_krx_login_env
from phase0.data.candidate_batch import EXPANDED_CANDIDATES
from scripts.spike_investor_flow import RETRO_FROM, RETRO_TO, _default_fetcher

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "investor_flow_spike"

# 상장일 대조용 소급 하한 — pykrx/KRX 데이터가 실질적으로 존재하는 최초
# 시점보다 넉넉히 앞선 날짜를 잡아, "2016-07 이전부터 이미 거래됐는지"를
# 판정한다.
LISTING_PROBE_FROM = "19980101"

# 최근 결측일 비율 확인 대상 거래일 수(§8 "결측일 비율 ≤5%").
RECENT_TRADING_DAYS = 10
# 위 거래일 수를 확실히 포함하도록 넉넉히 잡는 달력일 폭(공휴일 감안).
RECENT_CALENDAR_LOOKBACK_DAYS = 20

GATE_A_MIN_SUCCESS = 90
GATE_B_MAX_MISSING_RATIO = 0.05

API_SLEEP_SECONDS = 0.25


def _ohlcv_fetcher(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
    from pykrx import stock

    return stock.get_market_ohlcv(fromdate, todate, ticker)


@dataclass
class ListingCheck:
    checked: bool = False
    pre_window_ohlcv_rows: int | None = None
    first_trade_date_after_window: str | None = None
    listing_explained: bool = False
    error: str | None = None


@dataclass
class TickerFullResult:
    ticker: str
    retro_ok: bool = False
    retro_rows: int = 0
    retro_error: str | None = None
    listing_check: ListingCheck = field(default_factory=ListingCheck)
    recent_flow_rows: int = 0
    recent_flow_error: str | None = None
    recent_ohlcv_rows: int = 0
    recent_ohlcv_error: str | None = None
    recent_missing_days: int | None = None
    recent_missing_ratio: float | None = None


def check_listing_date(
    ticker: str,
    ohlcv_fetcher=_ohlcv_fetcher,
) -> ListingCheck:
    """2016-07 소급 실패 종목에 대해, 로그인이 필요 없는 OHLCV로 상장일
    전후를 대조한다.

    - LISTING_PROBE_FROM~RETRO_TO 구간에 OHLCV 행이 하나라도 있으면 =>
      이미 거래되고 있었는데 투자자별 수급만 없는 것이므로 "진짜 데이터
      문제"(listing_explained=False).
    - 그 구간에 OHLCV 행이 전혀 없으면 => RETRO_TO 다음날부터 오늘까지
      조회해 최초 거래일을 찾는다. 찾아지면 "상장일 때문에 정상적으로
      없는 것"(listing_explained=True). 그마저도 못 찾으면(코드 오류 등)
      원인 불명으로 남겨 사람이 확인하게 한다.
    """
    check = ListingCheck()
    try:
        pre_df = ohlcv_fetcher(LISTING_PROBE_FROM, RETRO_TO, ticker)
        check.pre_window_ohlcv_rows = len(pre_df)
    except Exception as exc:  # noqa: BLE001
        check.error = f"pre_window OHLCV 조회 오류: {type(exc).__name__}: {exc}"
        return check

    if check.pre_window_ohlcv_rows > 0:
        check.listing_explained = False
        check.checked = True
        return check

    after_from = (pd.Timestamp(RETRO_TO) + timedelta(days=1)).strftime("%Y%m%d")
    today = time.strftime("%Y%m%d")
    try:
        after_df = ohlcv_fetcher(after_from, today, ticker)
    except Exception as exc:  # noqa: BLE001
        check.error = f"post_window OHLCV 조회 오류: {type(exc).__name__}: {exc}"
        return check

    if len(after_df) > 0:
        check.first_trade_date_after_window = str(after_df.index.min().date())
        check.listing_explained = True
    else:
        check.error = (
            "OHLCV 전 구간(1998~오늘)에 데이터가 전혀 없음 — 종목코드 재사용/"
            "변경 등 다른 원인일 수 있어 상장일로 설명되지 않음. 수동 확인 필요."
        )
        check.listing_explained = False
    check.checked = True
    return check


def spike_one_ticker(
    ticker: str,
    recent_from: str,
    recent_to: str,
    flow_fetcher=_default_fetcher,
    ohlcv_fetcher=_ohlcv_fetcher,
) -> TickerFullResult:
    result = TickerFullResult(ticker=ticker)

    # (a) 2016-07 소급
    try:
        retro_df = flow_fetcher(RETRO_FROM, RETRO_TO, ticker)
        result.retro_rows = len(retro_df)
        result.retro_ok = result.retro_rows > 0
        if not result.retro_ok:
            result.retro_error = "빈 DataFrame 반환(2016-07 소급 실패)"
    except Exception as exc:  # noqa: BLE001
        result.retro_error = f"{type(exc).__name__}: {exc}"
    time.sleep(API_SLEEP_SECONDS)

    if not result.retro_ok:
        result.listing_check = check_listing_date(ticker, ohlcv_fetcher)
        time.sleep(API_SLEEP_SECONDS)

    # (b) 최근 결측일 비율
    try:
        recent_flow_df = flow_fetcher(recent_from, recent_to, ticker)
        result.recent_flow_rows = len(recent_flow_df)
    except Exception as exc:  # noqa: BLE001
        result.recent_flow_error = f"{type(exc).__name__}: {exc}"
    time.sleep(API_SLEEP_SECONDS)

    try:
        recent_ohlcv_df = ohlcv_fetcher(recent_from, recent_to, ticker)
        result.recent_ohlcv_rows = len(recent_ohlcv_df)
    except Exception as exc:  # noqa: BLE001
        result.recent_ohlcv_error = f"{type(exc).__name__}: {exc}"
    time.sleep(API_SLEEP_SECONDS)

    if result.recent_ohlcv_rows > 0:
        missing = max(0, result.recent_ohlcv_rows - result.recent_flow_rows)
        result.recent_missing_days = missing
        result.recent_missing_ratio = missing / result.recent_ohlcv_rows

    return result


def _resolve_recent_window(
    reference_ticker: str,
    n_trading_days: int = RECENT_TRADING_DAYS,
    lookback_days: int = RECENT_CALENDAR_LOOKBACK_DAYS,
    ohlcv_fetcher=_ohlcv_fetcher,
) -> tuple[str, str]:
    """기준 종목(대형·고유동성)의 실제 거래일을 이용해 '최근 N거래일'
    구간의 달력일 경계를 구한다. 공휴일 유무와 무관하게 정확히 N거래일을
    포함하는 [from, to]를 반환한다."""
    today = time.strftime("%Y%m%d")
    probe_from = (
        pd.Timestamp.today().normalize() - timedelta(days=lookback_days)
    ).strftime("%Y%m%d")
    df = ohlcv_fetcher(probe_from, today, reference_ticker)
    if len(df) < n_trading_days:
        # 대비책 — 조회 폭을 두 배로 늘려 재시도.
        probe_from = (
            pd.Timestamp.today().normalize() - timedelta(days=lookback_days * 2)
        ).strftime("%Y%m%d")
        df = ohlcv_fetcher(probe_from, today, reference_ticker)
    last_n = df.tail(n_trading_days)
    return str(last_n.index.min().date()).replace("-", ""), str(last_n.index.max().date()).replace("-", "")


def run_full_spike(
    tickers: list[str] = EXPANDED_CANDIDATES,
    flow_fetcher=_default_fetcher,
    ohlcv_fetcher=_ohlcv_fetcher,
) -> list[TickerFullResult]:
    recent_from, recent_to = _resolve_recent_window("005930", ohlcv_fetcher=ohlcv_fetcher)
    print(
        f"최근 {RECENT_TRADING_DAYS}거래일 구간(기준: 삼성전자 005930 실제 거래일): "
        f"{recent_from}~{recent_to}"
    )

    results: list[TickerFullResult] = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker} 조회 중...")
        results.append(
            spike_one_ticker(ticker, recent_from, recent_to, flow_fetcher, ohlcv_fetcher)
        )
        if i % 10 == 0 or i == len(tickers):
            n_retro_ok_so_far = sum(1 for r in results if r.retro_ok)
            print(f"  누적: {i}/{len(tickers)}종목 처리, 소급 성공 {n_retro_ok_so_far}건")
    return results


def build_gate_report(results: list[TickerFullResult]) -> dict:
    total = len(results)
    n_retro_ok = sum(1 for r in results if r.retro_ok)
    retro_failed = [r for r in results if not r.retro_ok]
    n_listing_explained = sum(1 for r in retro_failed if r.listing_check.listing_explained)
    n_genuine_problem = len(retro_failed) - n_listing_explained
    effective_success = n_retro_ok + n_listing_explained

    gate_a = {
        "total_tickers": total,
        "retro_ok_count": n_retro_ok,
        "retro_failed_count": len(retro_failed),
        "listing_explained_count": n_listing_explained,
        "genuine_data_problem_count": n_genuine_problem,
        "effective_success_count": effective_success,
        "threshold": GATE_A_MIN_SUCCESS,
        "passed": effective_success >= GATE_A_MIN_SUCCESS,
        "genuine_problem_tickers": [r.ticker for r in retro_failed if not r.listing_check.listing_explained],
        "listing_explained_tickers": [
            {"ticker": r.ticker, "first_trade_date": r.listing_check.first_trade_date_after_window}
            for r in retro_failed
            if r.listing_check.listing_explained
        ],
    }

    ratios = [r.recent_missing_ratio for r in results if r.recent_missing_ratio is not None]
    total_ohlcv_days = sum(r.recent_ohlcv_rows for r in results if r.recent_ohlcv_rows)
    total_missing_days = sum(r.recent_missing_days or 0 for r in results if r.recent_missing_days is not None)
    overall_missing_ratio = (total_missing_days / total_ohlcv_days) if total_ohlcv_days else None
    worst = sorted(
        (r for r in results if r.recent_missing_ratio is not None),
        key=lambda r: r.recent_missing_ratio,
        reverse=True,
    )[:10]

    gate_b = {
        "n_tickers_measured": len(ratios),
        "overall_missing_ratio": round(overall_missing_ratio, 4) if overall_missing_ratio is not None else None,
        "threshold": GATE_B_MAX_MISSING_RATIO,
        "passed": (overall_missing_ratio is not None and overall_missing_ratio <= GATE_B_MAX_MISSING_RATIO),
        "worst_offenders": [
            {"ticker": r.ticker, "missing_ratio": round(r.recent_missing_ratio, 4),
             "recent_flow_rows": r.recent_flow_rows, "recent_ohlcv_rows": r.recent_ohlcv_rows}
            for r in worst
        ],
    }

    return {
        "gate_a_retro_coverage": gate_a,
        "gate_b_missing_ratio": gate_b,
        "gates_a_b_passed": gate_a["passed"] and gate_b["passed"],
    }


def _result_to_dict(r: TickerFullResult) -> dict:
    d = asdict(r)
    return d


def _print_report(results: list[TickerFullResult], gate_report: dict) -> None:
    print("\n" + "=" * 70)
    print("게이트 (a)/(b) 95종목 전수 실측 결과 (§8 Phase 1 항목 4)")
    print("=" * 70)

    ga = gate_report["gate_a_retro_coverage"]
    gb = gate_report["gate_b_missing_ratio"]

    print(f"\n(a) 2016-07 소급: {ga['retro_ok_count']}/{ga['total_tickers']} 직접 성공, "
          f"실패 {ga['retro_failed_count']}건 중 상장일로 설명됨 {ga['listing_explained_count']}건, "
          f"진짜 데이터 문제 {ga['genuine_data_problem_count']}건")
    print(f"    => 실질 성공(상장일 설명분 포함) {ga['effective_success_count']}/{ga['total_tickers']}"
          f" (기준 >={ga['threshold']}) — {'PASS' if ga['passed'] else 'FAIL'}")
    if ga["genuine_problem_tickers"]:
        print(f"    진짜 데이터 문제 종목: {ga['genuine_problem_tickers']}")
    if ga["listing_explained_tickers"]:
        print(f"    상장일로 설명된 종목: {ga['listing_explained_tickers']}")

    print(f"\n(b) 최근 {RECENT_TRADING_DAYS}거래일 결측일 비율(전체 가중 평균): "
          f"{gb['overall_missing_ratio']} (기준 <={gb['threshold']}) — "
          f"{'PASS' if gb['passed'] else 'FAIL'}")
    if gb["worst_offenders"]:
        print("    결측률 최고 종목(상위 10):")
        for w in gb["worst_offenders"]:
            print(f"      {w['ticker']}: 결측률={w['missing_ratio']} "
                  f"(flow={w['recent_flow_rows']}/ohlcv={w['recent_ohlcv_rows']})")

    print(f"\n최종: {'게이트 (a)(b) 전부 통과' if gate_report['gates_a_b_passed'] else '미달 항목 있음'}")


def main() -> None:
    try:
        ensure_krx_login_env()
    except CredentialsMissingError as exc:
        print(f"오류: {exc}")
        sys.exit(1)

    results = run_full_spike()
    gate_report = build_gate_report(results)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "full_spike_report.json").write_text(
        json.dumps([_result_to_dict(r) for r in results], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (OUT_DIR / "gate_ab_report.json").write_text(
        json.dumps(gate_report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    _print_report(results, gate_report)
    print(f"\n산출물: {OUT_DIR}")


if __name__ == "__main__":
    main()
