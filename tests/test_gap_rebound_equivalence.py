"""GDR 리팩터 회귀 안전망 — gap_rebound_signal()의 관측 가능한 동작이
바이트 단위로 불변임을 증명하는 등가성/경계 커버리지 테스트 (B3 시그널 탭 작업).

배경: gap_rebound_signal()은 paper_trade_gdr.py / paper_trade_etf_gdr.py가
매 영업일 아침 실제로(페이퍼) 호출해 홀드아웃 데이터를 축적하는 라이브 함수다.
조건별 상세를 노출하기 위한 리팩터가 이 함수의 출력을 단 한 입력에서라도
바꾸면 그 홀드아웃이 조용히 오염된다. 그래서 리팩터 이전 코드의 동작을
**독립적으로 재구현한 오라클**(아래 _oracle_signal)을 이 파일에 고정해 두고,
수천 개의 합성 시나리오에서 gap_rebound_signal(...)의 결과가 오라클과 정확히
일치하는지 확인한다.

방법론: 이 오라클은 리팩터 이전 gap_rebound.py의 로직을 한 글자도 바꾸지 않고
옮겨 적은 것이다(상수만 import). 이 테스트를 (1) 리팩터 전 코드에 대해 통과
확인 → (2) 리팩터 → (3) 동일 테스트가 바이트 동일하게 다시 통과 확인, 이
3단계가 리팩터의 동작 보존 증명이다.
"""

from phase0.backtest.g0_backtester import Signal
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.gap_rebound import (
    ATR_BAND, EX_DIV_WINDOW, GAP_CAP, GAP_FLOOR_ABS, GAP_FLOOR_ATR, MIN_HISTORY,
    PREREGISTERED_GRID, PREV_DAY_CRASH, TREND_FLOOR, gap_rebound_signal,
)
from phase0.strategy.vcb_gap import round_up_to_tick


# ---------------------------------------------------------------------------
# 오라클 — 리팩터 이전 gap_rebound_signal()의 동작을 그대로 옮긴 고정 스냅샷.
# 이 함수는 절대 gap_rebound.py의 리팩터된 내부(evaluate_conditions 등)를
# 참조하지 않는다 — 오직 공개 상수만 쓰고 나머지는 자체 계산한다.
# ---------------------------------------------------------------------------
def _oracle_true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _oracle_signal(bars, today_open, today_date, f_fill=0.8, k_stop=1.0):
    if len(bars) < MIN_HISTORY:
        return None

    if EX_DIV_WINDOW[0] <= today_date[4:8] <= EX_DIV_WINDOW[1]:
        return None

    y, prev = bars[-1], bars[-2]

    sma20 = sum(b.close for b in bars[-20:]) / 20

    trs = [
        _oracle_true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])
    ]
    atr14 = sum(trs) / len(trs)
    atr_pct = atr14 / y.close

    gap = today_open / y.close - 1

    if not (y.close >= TREND_FLOOR * sma20):
        return None
    gap_floor = max(GAP_FLOOR_ABS, GAP_FLOOR_ATR * atr_pct)
    if not (-GAP_CAP <= gap <= -gap_floor):
        return None
    if not (y.close / prev.close - 1 > PREV_DAY_CRASH):
        return None
    if not (ATR_BAND[0] <= atr_pct <= ATR_BAND[1]):
        return None

    target = today_open + f_fill * (y.close - today_open)
    stop = today_open * (1 - k_stop * atr_pct)

    return Signal(
        date=today_date,
        entry_price=today_open,
        target_price=round_up_to_tick(target),
        stop_price=round_up_to_tick(stop),
    )


# ---------------------------------------------------------------------------
# 합성 봉 생성기 — sma20/atr/gap/전일수익률 각각을 독립적으로 흔들 수 있게 한다.
# ---------------------------------------------------------------------------
def _bar(date, close, half_range):
    return OhlcvBar(
        date=date, open=close, high=close + half_range, low=close - half_range,
        close=close, volume=1000,
    )


def _build_bars(n, bg_close, bg_half, prev_close, y_close, y_half):
    """n개 봉: [배경 n-2개] + [PREV(=bars[-2])] + [Y(=bars[-1], D-1)]."""
    bars = [_bar(f"D{i:02d}", bg_close, bg_half) for i in range(n - 2)]
    bars.append(_bar("PREV", prev_close, bg_half))
    bars.append(_bar("Y", y_close, y_half))
    return bars


def _assert_same(a, b):
    """두 결과(None 또는 Signal)가 관측 가능한 수준에서 완전히 동일한지."""
    if a is None or b is None:
        assert a is None and b is None, f"None 불일치: {a!r} vs {b!r}"
        return
    assert a.date == b.date, f"date 불일치: {a.date} vs {b.date}"
    assert a.entry_price == b.entry_price, f"entry 불일치: {a.entry_price} vs {b.entry_price}"
    assert a.target_price == b.target_price, f"target 불일치: {a.target_price} vs {b.target_price}"
    assert a.stop_price == b.stop_price, f"stop 불일치: {a.stop_price} vs {b.stop_price}"


# 경계를 관통하도록 고른 갭 크기(절대/적응 최소, 상한, 얕음/깊음 전부 관통).
_GAP_MULTIPLIERS = [
    -0.070, -0.060, -0.050, -0.046, -0.045, -0.044, -0.040, -0.030,
    -0.020, -0.015, -0.0125, -0.012, -0.0115, -0.008, -0.005, 0.0, +0.010,
]

# MMDD 경계 포함 날짜(EX_DIV_WINDOW = ("1222","1231")).
_DATES = [
    "20260715",   # 평시
    "20261221",   # 창 하루 전
    "20261222",   # 창 시작(포함)
    "20261225",   # 창 내부
    "20261231",   # 창 끝(포함)
    "20270101",   # 창 다음 해 초
]


def test_equivalence_over_condition_boundary_grid():
    """기본 f_fill/k_stop로 조건 경계 공간 전체를 스윕하며 오라클과 등가 확인."""
    n_cases = 0
    for n in (21, 22, 23, 40):
        for bg_close in (9000.0, 10000.0, 10200.0):
            for prev_close in (9500.0, 10000.0, 10600.0):
                for y_half in (60.0, 150.0, 300.0, 620.0):
                    y_close = 10000.0
                    bars = _build_bars(n, bg_close, 100.0, prev_close, y_close, y_half)
                    for mult in _GAP_MULTIPLIERS:
                        today_open = y_close * (1 + mult)
                        for date in _DATES:
                            got = gap_rebound_signal(bars, today_open, date)
                            exp = _oracle_signal(bars, today_open, date)
                            _assert_same(got, exp)
                            n_cases += 1
    # 토큰 수준이 아니라 진짜 커버리지임을 못박는다.
    assert n_cases > 3000, f"커버리지 부족: {n_cases}건"


def test_equivalence_over_preregistered_grid_when_firing():
    """신호가 실제로 발동하는 시나리오들에서 6개 (f_fill,k_stop) 조합 전부 등가 확인.

    발동 시나리오에서만 target/stop 계산 경로가 실행되므로, 그 경로를
    격자 전체에 대해 검증한다.
    """
    n_cases = 0
    n_fired = 0
    # C1~C4를 만족하도록 조율된 발동 후보군 + 일부러 어긋난 것들 섞음.
    fire_specs = [
        (22, 10000.0, 10000.0, 150.0, -0.020),
        (22, 10000.0, 10000.0, 150.0, -0.025),
        (23, 10050.0, 10050.0, 150.0, -0.018),
        (30, 10000.0, 9900.0, 200.0, -0.030),
        (40, 10000.0, 10100.0, 250.0, -0.022),
        (22, 10000.0, 10000.0, 150.0, -0.005),   # 얕음 → 미발동(오라클과 함께 확인)
        (22, 10000.0, 10000.0, 800.0, -0.020),   # ATR 밴드 이탈 → 미발동
    ]
    for n, bg_close, prev_close, y_half, mult in fire_specs:
        y_close = 10000.0
        bars = _build_bars(n, bg_close, 100.0, prev_close, y_close, y_half)
        today_open = y_close * (1 + mult)
        for f_fill, k_stop in PREREGISTERED_GRID:
            got = gap_rebound_signal(bars, today_open, "20260715", f_fill=f_fill, k_stop=k_stop)
            exp = _oracle_signal(bars, today_open, "20260715", f_fill=f_fill, k_stop=k_stop)
            _assert_same(got, exp)
            if got is not None:
                n_fired += 1
            n_cases += 1
    assert n_cases == len(fire_specs) * len(PREREGISTERED_GRID)
    # 발동 경로(target/stop 계산)가 실제로 검증됐음을 보장.
    assert n_fired > 0, "발동 시나리오가 하나도 신호를 내지 않았다 — 격자 경로 미검증"


def test_equivalence_insufficient_history_boundary():
    """MIN_HISTORY 경계(21/22) 전후로 오라클과 등가."""
    y_close = 10000.0
    for n in range(18, 26):
        bars = [_bar(f"D{i:02d}", 10000.0, 100.0) for i in range(n)]
        today_open = y_close * 0.98
        got = gap_rebound_signal(bars, today_open, "20260715")
        exp = _oracle_signal(bars, today_open, "20260715")
        _assert_same(got, exp)
