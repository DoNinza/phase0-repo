"""Phase 1 데이터 스파이크 — 외국인 수급(FFD) 트랙 게이트 0 실측.

docs/foreign_flow_nat_전략_기획안.md §8 Phase 1 항목 2의 게이트 스크립트.
**수익률은 전혀 계산하지 않는다** — 이 단계는 순수하게 데이터 접근성만
잰다. 확인하는 것은 정확히 4가지:

  (a) 로그인 성공 여부 — get_market_trading_value_by_date가 JSON 파싱
      오류 없이 정상 DataFrame을 반환하는가(§2.2 실측 결과, 현재는
      로그인 없이 전부 "Expecting value: line 1 column 1" 오류로 깨져
      있다)
  (b) 2016-07 소급 가능 여부 — 표본 종목의 2016-07 조회가 실제로 행을
      반환하는가
  (c) 반환 컬럼 스키마 — pykrx 1.2.8이 실제로 반환하는 컬럼 이름 전수
  (d) 결측 처리 실태 — NaN/빈 값의 개수와 위치

**게이트 0 선결 조건(§8)**: 사용자가 아직 data.krx.co.kr 가입 전이라도
이 스크립트를 실행해볼 수 있게 하되, `.env`에 `KRX_ID`/`KRX_PW`가 없으면
명확한 안내와 함께 즉시 중단한다 — data.krx.co.kr 가입을 이 스크립트가
대신 하지 않는다(그건 사용자만 할 수 있는 계정 생성 행위).

이 스크립트는 §8이 요구하는 "95종목 전수 게이트 판정"(게이트 a/b/c:
매핑 ≥90종목, 결측 ≤5%, 신호 밀도)이 아니라 그 전 단계 — 표본 종목
5~10개로 먼저 감을 잡는 것이다. 로그인 자체가 뚫린다는 게 확인된
**이후**에만 95종목 전수 수집(Phase 3 investor_flow_ingest.py)으로
넘어간다.

사용법:
    python scripts/spike_investor_flow.py

산출물(전부 .gitignore 처리된 data/investor_flow_spike/ 아래, 소스코드
아님): spike_report.json — 종목별 결과(로그인/소급/스키마/결측) 전체.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from phase0.config.krx_credentials import CredentialsMissingError, ensure_krx_login_env
from phase0.data.candidate_batch import EXPANDED_CANDIDATES

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "investor_flow_spike"

# 표본 종목 — EXPANDED_CANDIDATES 앞쪽 8개(요구 범위 5~10개 안).
SAMPLE_TICKERS = EXPANDED_CANDIDATES[:8]

# 최근 구간(로그인·스키마 확인용) — 실행 시점 기준 최근 2주.
RECENT_DAYS = 14

# 소급 확인 구간(§2.2 "2016년까지 소급될 것으로 기대"의 실측 대상).
RETRO_FROM = "20160701"
RETRO_TO = "20160731"

Fetcher = Callable[[str, str, str], pd.DataFrame]


def _default_fetcher(fromdate: str, todate: str, ticker: str) -> pd.DataFrame:
    from pykrx import stock
    return stock.get_market_trading_value_by_date(
        fromdate, todate, ticker, on="순매수", detail=True
    )


@dataclass
class TickerSpikeResult:
    ticker: str
    recent_ok: bool = False
    recent_error: str | None = None
    recent_columns: list[str] = field(default_factory=list)
    recent_rows: int = 0
    recent_na_counts: dict[str, int] = field(default_factory=dict)
    retro_ok: bool = False
    retro_error: str | None = None
    retro_rows: int = 0


def _inspect(df: pd.DataFrame) -> tuple[list[str], dict[str, int]]:
    columns = [str(c) for c in df.columns]
    na_counts = {str(c): int(df[c].isna().sum()) for c in df.columns}
    return columns, na_counts


def spike_one_ticker(
    ticker: str,
    recent_from: str,
    recent_to: str,
    fetcher: Fetcher = _default_fetcher,
) -> TickerSpikeResult:
    """표본 종목 하나에 대해 최근 구간(로그인/스키마)과 2016-07 구간(소급)을
    각각 호출한다. 한 종목의 실패가 나머지 종목 수집을 막지 않도록 종목
    단위로 예외를 격리한다(spike_dart_events.py와 동일 원칙)."""
    result = TickerSpikeResult(ticker=ticker)

    try:
        recent_df = fetcher(recent_from, recent_to, ticker)
        columns, na_counts = _inspect(recent_df)
        result.recent_columns = columns
        result.recent_na_counts = na_counts
        result.recent_rows = len(recent_df)
        result.recent_ok = len(recent_df) > 0
        if not result.recent_ok:
            result.recent_error = "빈 DataFrame 반환(로그인 실패 또는 데이터 없음)"
    except Exception as exc:  # noqa: BLE001
        result.recent_error = f"{type(exc).__name__}: {exc}"

    try:
        retro_df = fetcher(RETRO_FROM, RETRO_TO, ticker)
        result.retro_rows = len(retro_df)
        result.retro_ok = len(retro_df) > 0
        if not result.retro_ok:
            result.retro_error = "빈 DataFrame 반환(2016-07 소급 실패 또는 로그인 실패)"
    except Exception as exc:  # noqa: BLE001
        result.retro_error = f"{type(exc).__name__}: {exc}"

    return result


def run_spike(
    tickers: list[str] = SAMPLE_TICKERS,
    fetcher: Fetcher = _default_fetcher,
    recent_days: int = RECENT_DAYS,
) -> list[TickerSpikeResult]:
    recent_to = time.strftime("%Y%m%d")
    recent_from = (
        pd.Timestamp.today().normalize() - pd.Timedelta(days=recent_days)
    ).strftime("%Y%m%d")

    results: list[TickerSpikeResult] = []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker} 조회 중...")
        results.append(spike_one_ticker(ticker, recent_from, recent_to, fetcher))
        time.sleep(0.2)
    return results


def _print_report(results: list[TickerSpikeResult]) -> None:
    print("\n" + "=" * 70)
    print("게이트 0 스파이크 결과 (§8 Phase 1 항목 2)")
    print("=" * 70)

    n_login_ok = sum(1 for r in results if r.recent_ok)
    n_retro_ok = sum(1 for r in results if r.retro_ok)

    print(f"\n(a) 로그인 성공 여부: {n_login_ok}/{len(results)}종목에서 정상 응답 수신")
    print(f"(b) 2016-07 소급 가능 여부: {n_retro_ok}/{len(results)}종목에서 데이터 수신")

    all_columns: set[str] = set()
    for r in results:
        all_columns.update(r.recent_columns)
    schema_display = sorted(all_columns) if all_columns else "(없음 — 응답 전부 실패)"
    print(f"(c) 반환 컬럼 스키마(표본 종목 합집합): {schema_display}")

    print("(d) 결측 처리 실태(종목별 최근 구간 NA 개수):")
    for r in results:
        status = "OK" if r.recent_ok else f"FAIL({r.recent_error})"
        print(f"    {r.ticker}: {status}, rows={r.recent_rows}, na={r.recent_na_counts}")

    print("\n종목별 상세:")
    for r in results:
        print(
            f"  {r.ticker}: recent_ok={r.recent_ok} "
            f"({r.recent_error or 'OK'}), retro_ok={r.retro_ok} "
            f"({r.retro_error or 'OK'})"
        )

    if n_login_ok == 0:
        print(
            "\n결론: 전 종목 로그인 실패 — pykrx KRX_ID/KRX_PW 경로가 이 계정으로는 "
            "뚫리지 않는 것으로 보인다. §8 게이트 0 실패. docs/"
            "foreign_flow_nat_전략_기획안.md §2.4의 대안소스(KRX 공식 Open API "
            "openapi.krx.co.kr 등) 검토 또는 트랙 보류를 검토하라. 이건 '기각'이 "
            "아니라 '게이트0 차단'이다(§9.4 구분 — 데이터 부재이지 엣지 부재가 아니다)."
        )
    elif n_login_ok < len(results):
        print(
            f"\n결론: 일부 종목({len(results) - n_login_ok}개)만 실패 — 종목별 상세를 "
            "확인해 일시적 오류인지 계정·종목 문제인지 판단하라."
        )
    else:
        print("\n결론: 표본 전 종목 로그인 성공 — 게이트 0(로그인) 잠정 통과.")
        if n_retro_ok < len(results):
            print(
                f"      단, 2016-07 소급은 {n_retro_ok}/{len(results)}종목만 성공 — "
                "§8 게이트 (a) 95종목 전수 실측 시 이 실패율을 반드시 재확인하라."
            )
        else:
            print("      2016-07 소급도 표본 전 종목 성공 — Phase 1 전수 수집으로 진행 가능.")


def main() -> None:
    try:
        ensure_krx_login_env()
    except CredentialsMissingError as exc:
        print(f"오류: {exc}")
        sys.exit(1)

    results = run_spike()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "spike_report.json").write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print_report(results)
    print(f"\n산출물: {OUT_DIR}")


if __name__ == "__main__":
    main()
