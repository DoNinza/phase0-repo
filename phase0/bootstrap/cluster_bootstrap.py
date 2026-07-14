"""거래일 클러스터 통합 부트스트랩 (기획안 §5.7, R-08).

문제의식: 계좌 지표(CAGR·MDD 등)는 일별 수익률 단위, 거래 지표(E_trade·p·W·L)는
거래 단위인데, 둘을 서로 다른 부트스트랩으로 따로 돌리면(외부 제안: "2개 분리
부트스트랩") 같은 날짜의 계좌 성과와 그날 실제로 일어난 거래 집합이 재표본
과정에서 분리되어 버린다.

채택안(통합안): 재표본의 단위를 "날짜 블록"으로 하고, 블록에 포함된 각 날짜의
(그날 계좌 수익률, 그날 거래 목록)을 쌍으로 유지한다. 한 번의 재표본 경로 안에서
계좌 지표와 거래 지표를 동시에, 일관되게 산출한다 — 동일 날짜 거래를 독립
표본으로 취급하는 오류가 구조적으로 제거된다.

주의(§5.7 명시): 파라미터 선택 후 CI는 낙관 편향이 있다는 것을 인정하고,
최종 보고 CI는 반드시 홀드아웃 구간 것을 병기한다. 이 모듈은 그 최종 보고용
숫자를 만드는 도구이지, 그 자체로 판정 근거가 되지는 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class DailyRecord:
    """하루치 원자료. trades는 그날 종료된 거래들의 결과 목록."""
    date: str
    account_return: float          # 그날의 계좌 수익률 (소수)
    trades: list[dict] = field(default_factory=list)
    # 각 trade dict 형태 예: {"pnl_pct": 0.012, "is_win": True}


@dataclass
class BootstrapResult:
    account_metrics: dict[str, np.ndarray]   # 지표명 -> (n_resamples,) 배열
    trade_metrics: dict[str, np.ndarray]

    def ci(self, metric_group: str, name: str, lo: float = 2.5, hi: float = 97.5) -> tuple[float, float]:
        arr = getattr(self, metric_group)[name]
        return (float(np.percentile(arr, lo)), float(np.percentile(arr, hi)))


def _account_metrics_from_path(daily_returns: Sequence[float]) -> dict[str, float]:
    """한 재표본 경로(일별 수익률 시퀀스)에서 계좌 지표 계산."""
    equity = np.cumprod(1 + np.asarray(daily_returns, dtype=float))
    total_days = len(equity)
    cagr = equity[-1] ** (248 / total_days) - 1 if total_days > 0 else 0.0
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1
    mdd = float(drawdown.min()) if len(drawdown) else 0.0
    # 최악 구간(worst_period): 최대 낙폭이 시작된 뒤 회복 전까지의 길이(거래일)
    if len(drawdown):
        trough_idx = int(np.argmin(drawdown))
        peak_idx = int(np.argmax(equity[: trough_idx + 1]))
        worst_period = trough_idx - peak_idx
    else:
        worst_period = 0
    return {"cagr": float(cagr), "mdd": mdd, "worst_period_days": float(worst_period)}


def _trade_metrics_from_trades(trades: Sequence[dict]) -> dict[str, float]:
    """한 재표본 경로에 포함된 거래 전체에서 p, W, L, E_trade(비용 미포함 총이) 계산."""
    if not trades:
        return {"p": float("nan"), "W": float("nan"), "L": float("nan"), "e_trade_gross": float("nan")}
    pnls = np.array([t["pnl_pct"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    p = len(wins) / len(pnls)
    W = float(wins.mean()) if len(wins) else 0.0
    L = float(-losses.mean()) if len(losses) else 0.0
    e_trade_gross = float(pnls.mean())  # 비용 미차감 — 비용은 phase0.config.costs에서 별도 적용
    return {"p": p, "W": W, "L": L, "e_trade_gross": e_trade_gross}


def moving_block_bootstrap(
    daily_records: Sequence[DailyRecord],
    block_length: int = 15,
    n_resamples: int = 1000,
    rng: np.random.Generator | None = None,
) -> BootstrapResult:
    """날짜 블록 단위 이동 블록 부트스트랩.

    block_length: 블록 길이(거래일). 기본 15일 [초기 가정] — 리포트에는
    10/15/20일 민감도를 함께 표기한다(block_length_sensitivity 참고).
    """
    rng = rng or np.random.default_rng()
    n = len(daily_records)
    if n < block_length:
        raise ValueError(f"daily_records 길이({n})가 block_length({block_length})보다 작습니다.")

    n_blocks_needed = -(-n // block_length)  # ceil
    max_start = n - block_length

    account_metric_names = ["cagr", "mdd", "worst_period_days"]
    trade_metric_names = ["p", "W", "L", "e_trade_gross"]
    account_out = {k: np.empty(n_resamples) for k in account_metric_names}
    trade_out = {k: np.empty(n_resamples) for k in trade_metric_names}

    for i in range(n_resamples):
        starts = rng.integers(0, max_start + 1, size=n_blocks_needed)
        path_records: list[DailyRecord] = []
        for s in starts:
            path_records.extend(daily_records[s: s + block_length])
        path_records = path_records[:n]  # 원 표본과 동일 길이로 자르기

        daily_returns = [r.account_return for r in path_records]
        all_trades = [t for r in path_records for t in r.trades]

        am = _account_metrics_from_path(daily_returns)
        tm = _trade_metrics_from_trades(all_trades)
        for k in account_metric_names:
            account_out[k][i] = am[k]
        for k in trade_metric_names:
            trade_out[k][i] = tm[k]

    return BootstrapResult(account_metrics=account_out, trade_metrics=trade_out)


def block_length_sensitivity(
    daily_records: Sequence[DailyRecord],
    block_lengths: Sequence[int] = (10, 15, 20),
    n_resamples: int = 1000,
    rng: np.random.Generator | None = None,
) -> dict[int, BootstrapResult]:
    """블록 길이 민감도 확인 (§5.7: '블록 길이 민감도는 리포트에 참고 표기')."""
    rng = rng or np.random.default_rng()
    return {bl: moving_block_bootstrap(daily_records, block_length=bl, n_resamples=n_resamples, rng=rng)
            for bl in block_lengths}
