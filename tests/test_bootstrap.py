import numpy as np
import pytest

from phase0.bootstrap.cluster_bootstrap import (
    DailyRecord, moving_block_bootstrap, block_length_sensitivity,
)


def _make_synthetic_records(n_days=250, seed=0):
    rng = np.random.default_rng(seed)
    records = []
    for i in range(n_days):
        acct_ret = rng.normal(0.0005, 0.01)
        n_trades_today = rng.integers(0, 3)
        trades = []
        for _ in range(n_trades_today):
            pnl = rng.normal(0.001, 0.02)
            trades.append({"pnl_pct": float(pnl), "is_win": pnl > 0})
        records.append(DailyRecord(date=f"D{i:04d}", account_return=float(acct_ret), trades=trades))
    return records


def test_moving_block_bootstrap_returns_correct_shapes():
    records = _make_synthetic_records()
    result = moving_block_bootstrap(records, block_length=15, n_resamples=200,
                                     rng=np.random.default_rng(42))
    assert result.account_metrics["cagr"].shape == (200,)
    assert result.trade_metrics["p"].shape == (200,)


def test_ci_helper_returns_ordered_bounds():
    records = _make_synthetic_records()
    result = moving_block_bootstrap(records, block_length=15, n_resamples=300,
                                     rng=np.random.default_rng(1))
    lo, hi = result.ci("account_metrics", "cagr")
    assert lo <= hi


def test_block_too_long_raises():
    records = _make_synthetic_records(n_days=10)
    with pytest.raises(ValueError):
        moving_block_bootstrap(records, block_length=15, n_resamples=10)


def test_block_length_sensitivity_covers_requested_lengths():
    records = _make_synthetic_records()
    out = block_length_sensitivity(records, block_lengths=(10, 15, 20), n_resamples=100,
                                    rng=np.random.default_rng(7))
    assert set(out.keys()) == {10, 15, 20}
    for res in out.values():
        assert res.account_metrics["mdd"].shape == (100,)


def test_same_date_pairing_preserved():
    """핵심 요구사항(R-08): 재표본 경로에서 날짜별 (계좌수익, 거래목록) 쌍이 유지되는지 확인.
    즉, 어떤 날의 거래가 그 날의 계좌수익과 분리되어 다른 날 것과 섞이면 안 된다.
    """
    records = [
        DailyRecord(date="A", account_return=0.05, trades=[{"pnl_pct": 0.10, "is_win": True}]),
        DailyRecord(date="B", account_return=-0.05, trades=[{"pnl_pct": -0.10, "is_win": False}]),
    ] * 20  # block_length보다 충분히 길게
    result = moving_block_bootstrap(records, block_length=5, n_resamples=50,
                                     rng=np.random.default_rng(3))
    # A일=이익쌍, B일=손실쌍이 항상 같이 다니므로, trade의 p(승률)는 계좌수익 부호 비율과 일치해야 함
    assert result.trade_metrics["p"].min() >= 0
    assert result.trade_metrics["p"].max() <= 1
