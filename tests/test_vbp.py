from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vbp import PREREGISTERED_GRID, vbp_signal


def _flat(date, o=10000, h=10100, l=9900, c=10000, v=1000):
    return OhlcvBar(date=date, open=o, high=h, low=l, close=c, volume=v)


def _base_bars():
    """indices 0..21: 평범한 배경 20+2봉. index22: 거래량 동반 결정적 돌파(앵커,D-2).
    index23: 거래량 수축 속 눌림(D-1, 레벨 위 유지)."""
    bars = [_flat(f"D{i:02d}") for i in range(22)]
    anchor = OhlcvBar(date="D22", open=10100, high=10500, low=10050, close=10450, volume=3000)
    pullback = OhlcvBar(date="D23", open=10150, high=10300, low=10150, close=10200, volume=1500)
    bars.append(anchor)
    bars.append(pullback)
    return bars


TODAY_OPEN = 10200 * 0.99   # 갭 -0.98% — C6 밴드[-3.5%,0%] 통과
TODAY_DATE = "D24"


def test_preregistered_grid_has_six_combinations():
    assert len(PREREGISTERED_GRID) == 6
    assert (0.75, 1.25) in PREREGISTERED_GRID


def test_none_when_insufficient_history():
    bars = _base_bars()[:23]
    assert vbp_signal(bars, TODAY_OPEN, TODAY_DATE) is None


def test_fires_when_anchor_and_pullback_valid():
    bars = _base_bars()
    sig = vbp_signal(bars, TODAY_OPEN, TODAY_DATE)
    assert sig is not None
    assert sig.entry_price == TODAY_OPEN
    assert sig.target_price > sig.entry_price   # 스윙고점 방향 되돌림
    assert sig.stop_price < sig.entry_price     # 구조(레벨) 기준 손절


def test_rejects_when_no_breakout_anchor_exists():
    """배경 전체가 평범하면(어느 offset도 C1 미달) 앵커 자체가 없어 신호 없음."""
    bars = [_flat(f"D{i:02d}") for i in range(24)]
    assert vbp_signal(bars, TODAY_OPEN, TODAY_DATE) is None


def test_rejects_when_post_anchor_close_breaches_level():
    """돌파 후 종가가 레벨 아래로 내려간 적 있으면(휩쏘 시그니처) C4 위반으로 거부."""
    bars = _base_bars()
    bars[23] = OhlcvBar(date="D23", open=10000, high=10080, low=9950, close=10050, volume=1500)
    assert vbp_signal(bars, TODAY_OPEN, TODAY_DATE) is None


def test_rejects_when_pullback_volume_not_contracted():
    """눌림 구간 거래량이 앵커일 대비 충분히 줄지 않으면(분산 의심) C5 위반으로 거부."""
    bars = _base_bars()
    bars[23] = OhlcvBar(date="D23", open=10150, high=10300, low=10150, close=10200, volume=2500)
    assert vbp_signal(bars, TODAY_OPEN, TODAY_DATE) is None


def test_rejects_when_gap_is_positive():
    """C6은 약세~보합 시가만 허용 — 갭상승이면 거부."""
    bars = _base_bars()
    positive_gap_open = bars[-1].close * 1.01
    assert vbp_signal(bars, positive_gap_open, TODAY_DATE) is None


def test_rejects_ex_dividend_window_regardless_of_other_conditions():
    bars = _base_bars()
    assert vbp_signal(bars, TODAY_OPEN, "20261225") is None


def test_f_ret_and_k_stop_change_target_and_stop_price():
    bars = _base_bars()
    default_sig = vbp_signal(bars, TODAY_OPEN, TODAY_DATE, f_ret=0.5, k_stop=0.75)
    fuller_sig = vbp_signal(bars, TODAY_OPEN, TODAY_DATE, f_ret=1.0, k_stop=1.25)

    assert fuller_sig.target_price > default_sig.target_price   # 더 많이 되돌림
    assert fuller_sig.stop_price < default_sig.stop_price        # k_stop 커짐 → 손절 더 멀어짐
