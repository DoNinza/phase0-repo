#!/usr/bin/env python3
"""GDR 신호에 대한 ML 스마트 필터 학습 + OOS 평가 (2026-07-15).

배경: 4개 규칙 기반 가설(VCB-Gap/GDR/GDR-V/VBP)이 전부 실데이터로 기각·
근거소멸됐다(README 참고). 완전히 새 신호 생성 로직을 만드는 대신, 이미
만든 GDR(f_fill=1.0, k_stop=1.0 — 95종목 사전등록 격자 6개 중 최선 조합,
이 스크립트를 만들기 전에 이미 확정된 선택이지 결과를 보고 고른 게 아님)
신호 위에서 "이 신호가 이길 확률"을 로지스틱 회귀로 추정해 승률 낮은
신호를 거르는 스마트 필터를 만든다.

과적합 방지 설계(전부 결과를 보기 전에 고정):
- 하이퍼파라미터(C=1.0, class_weight="balanced")는 그리드서치로 튜닝하지 않는다.
- 학습/평가는 날짜 기준 워크포워드 분할(시간순 80%/20%) — 미래로 과거를 학습하지 않는다.
- OOS(평가) 구간은 학습 중 전혀 보지 않고, 평가도 단 한 번만 한다.
- 필터 임계값(P(win)>=0.5)도 사전 고정.

pytest에는 포함하지 않는다 — 여러 종목·다년치 실제 네트워크 호출.

사용법: python scripts/train_gdr_ml_filter.py [--universe default|expanded] [--years N]
"""

from __future__ import annotations

import datetime as dt
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from phase0.backtest.g0_backtester import resolve_trade
from phase0.config.costs import base_breakdown
from phase0.data.candidate_batch import DEFAULT_CANDIDATES, EXPANDED_CANDIDATES
from phase0.data.pykrx_ingest import fetch_ohlcv, to_daily_bar
from phase0.ml.gdr_filter import FEATURE_NAMES, extract_features, to_vector
from phase0.strategy.gap_rebound import gap_rebound_signal

UNIVERSES = {"default": DEFAULT_CANDIDATES, "expanded": EXPANDED_CANDIDATES}

# 사전 확정 — 95종목 격자 실험(README)에서 이미 나온 최선 조합을 그대로 승계.
F_FILL, K_STOP = 1.0, 1.0
TRAIN_FRACTION = 0.8      # 날짜 기준 시간순 분할 — 사전 확정
WIN_PROB_THRESHOLD = 0.5  # 사전 확정


def generate_signals_with_features(bars, ticker):
    rows = []
    for i, b in enumerate(bars):
        history = bars[:i]   # D 이전(=D-1까지) — 룩어헤드 없음
        sig = gap_rebound_signal(history, b.open, b.date, f_fill=F_FILL, k_stop=K_STOP)
        if sig is None:
            continue
        try:
            feats = extract_features(history, b.open, b.date)
        except ValueError:
            continue
        rows.append((ticker, sig, feats))
    return rows


def e_trade_of(trades, cost_base):
    if not trades:
        return float("nan"), 0, float("nan")
    pnls = [t.pnl_pct for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    p = len(wins) / len(pnls)
    W = sum(wins) / len(wins) if wins else 0.0
    L = -sum(losses) / len(losses) if losses else 0.0
    return p * W - (1 - p) * L - cost_base, len(pnls), p


def main() -> None:
    universe = "expanded"
    years = 10
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--universe":
            universe = args[i + 1]
        if a == "--years":
            years = int(args[i + 1])
    tickers = UNIVERSES[universe]

    end = dt.date.today().strftime("%Y%m%d")
    start = (dt.date.today() - dt.timedelta(days=365 * years)).strftime("%Y%m%d")

    print(f"GDR ML 필터 학습: {len(tickers)}종목({universe}), {start}~{end}")
    print(f"라벨링에 쓰는 GDR 조합(사전 확정, 95종목 격자 최선): f_fill={F_FILL}, k_stop={K_STOP}\n")

    all_rows = []
    daily_bars_by_ticker = {}
    for t in tickers:
        try:
            raw = fetch_ohlcv(t, start, end)
        except Exception as exc:
            print(f"  {t}: 수집 실패 ({type(exc).__name__}: {exc})")
            continue
        daily_bars_by_ticker[t] = {b.date: to_daily_bar(b) for b in raw}
        all_rows.extend(generate_signals_with_features(raw, t))

    print(f"\n총 신호 수: {len(all_rows)}")
    cost_base = base_breakdown().base_total

    dates_sorted = sorted({sig.date for _, sig, _ in all_rows})
    cutoff_idx = int(len(dates_sorted) * TRAIN_FRACTION)
    cutoff_date = dates_sorted[cutoff_idx]
    print(f"학습/평가 분할 기준일(시간순 {TRAIN_FRACTION:.0%} 지점): {cutoff_date}")

    train_rows = [r for r in all_rows if r[1].date < cutoff_date]
    test_rows = [r for r in all_rows if r[1].date >= cutoff_date]
    print(f"학습 신호: {len(train_rows)}건, 평가(OOS) 신호: {len(test_rows)}건\n")

    def resolve(ticker, sig):
        bar = daily_bars_by_ticker[ticker][sig.date]
        return resolve_trade(bar, sig, "conservative")

    X_train = np.array([to_vector(f) for _, _, f in train_rows])
    y_train = np.array([resolve(t, s).is_win for t, s, _ in train_rows])
    X_test = np.array([to_vector(f) for _, _, f in test_rows])
    y_test_trades = [resolve(t, s) for t, s, _ in test_rows]

    scaler = StandardScaler().fit(X_train)
    X_train_s = scaler.transform(X_train)
    X_test_s = scaler.transform(X_test)

    model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000)
    model.fit(X_train_s, y_train)

    print("=== 특징 계수(표준화 후, |값| 큰 순서, 양수=승리와 정방향) ===")
    for name, coef in sorted(zip(FEATURE_NAMES, model.coef_[0]), key=lambda x: -abs(x[1])):
        print(f"  {name:>16}: {coef:+.4f}")

    train_win_rate = float(y_train.mean())
    print(f"\n학습 구간 원 GDR 승률(IS): {train_win_rate * 100:.2f}%")

    win_prob = model.predict_proba(X_test_s)[:, 1]
    filtered_mask = win_prob >= WIN_PROB_THRESHOLD

    baseline_e, baseline_n, baseline_p = e_trade_of(y_test_trades, cost_base)
    filtered_trades = [t for t, m in zip(y_test_trades, filtered_mask) if m]
    filtered_e, filtered_n, filtered_p = e_trade_of(filtered_trades, cost_base)

    print(f"\n=== OOS 비교 (기준일 {cutoff_date} 이후, 동일 기간, 동일 비용 {cost_base*100:.4f}%) ===")
    print(f"필터 없음(원 GDR):        {baseline_n:>5}건, 승률 {baseline_p*100:.2f}%, E_trade = {baseline_e*100:+.4f}%")
    print(f"ML 필터(P(win)>={WIN_PROB_THRESHOLD}):    {filtered_n:>5}건, 승률 {filtered_p*100:.2f}%, E_trade = {filtered_e*100:+.4f}%")


if __name__ == "__main__":
    main()
