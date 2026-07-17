"""PEAD 전략: 분기 잠정실적 서프라이즈 후 드리프트 (fable5 설계, 2026-07-17).

뉴스·펀더멘털 기반 전략 트랙 — GDR(순수 가격 데이터)과 병렬로 검증하는
별도 가설. 배경·데이터소스·근거는 docs/news_fundamentals_전략_기획안.md
(Phase 1 실행 결과는 같은 문서 §10, README "PEAD Phase 1 데이터 스파이크
실행" 참고).

이 모듈은 **Phase 2 산출물** — 사전등록 파라미터를 코드로 확정 커밋하는
자리다(기획안 §8 "§5의 모든 초안 항목을 단일 값/격자로 확정해
phase0/strategy/pead.py 모듈 상수 + 본 문서 갱신으로 커밋"). 이 시점까지
백테스트 결과는 전혀 보지 않았다 — 아래 상수는 순수하게 데이터 안정성·
가용성·기존 컨벤션 근거로만 정했다(gap_rebound.py의 "결과 보고 조정
금지" 원칙과 동일). **이 커밋 이후 백테스트 결과를 보기 전까지 어떤
항목도 수정하지 않는다.**

Phase 3(백테스트 하네스·이벤트 수집): `compute_sue`/`pead_signal`은 Phase 3에서
추가됐다 — §5에서 확정된 상수(위)만 쓰고, 신호 판정 로직 자체는 결과를
보고 조정한 적 없다(상수 확정 커밋 이후 변경 없음, git log로 확인 가능).
"""

from __future__ import annotations

from phase0.backtest.event_backtester import EventSignal
from phase0.data.dart_ingest import DartEvent
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vcb_gap import round_up_to_tick

MIN_ATR_HISTORY = 15  # ATR14 계산에 필요한 최소 일봉 수(gap_rebound.py MIN_HISTORY와 같은 역할)

# ---------------------------------------------------------------------------
# SUE(Standardized Unexpected Earnings) 분모 — 사전등록 확정, 2026-07-17
# ---------------------------------------------------------------------------
# 후보 3개(기획안 §3): (a) |OP_{q-4}|, (b) 당기 매출액, (c) 전일 시가총액.
# "매출액"을 확정한다. 근거:
#   1. (a) |OP_{q-4}|는 영업이익이 0 근처이거나 음수인 분기에서 분모가
#      폭주·부호역전한다 — Phase 1 스파이크 표본에서 실제로 전년동기
#      영업이익이 적자(음수)였던 케이스가 관측됨(009830 한화솔루션,
#      data/dart_spike/parse_samples.json 실측), 윈저라이즈 없이는 SUE가
#      통제 불능으로 튄다.
#   2. (c) 시가총액은 이 표(잠정실적 공시)에 없는 별도 데이터(발행주식수×
#      가격)가 필요해 데이터 의존성·실패 표면이 늘어난다.
#   3. (b) 매출액은 실질적으로 0에 가까워질 위험이 없고(정상 영업 중인
#      상장사 기준), Phase 1에서 이미 검증된 동일 파서(attempt_parse_figures
#      와 동일한 표 구조 — "매출액" 행도 "영업이익" 행과 같은 컬럼
#      레이아웃)로 바로 뽑을 수 있어 추가 파싱 리스크가 없다.
SUE_DENOMINATOR = "sales"  # "sales" = 당기 매출액. 다른 값 사용 금지(사전등록).

# ---------------------------------------------------------------------------
# 사전등록 격자 (기획안 §5, 총 2x2x2 = 8칸) — 전수 보고, 최선 칸만 채택 금지
# ---------------------------------------------------------------------------
# SUE 진입 임계값(θ) — 매출액 대비 서프라이즈 비율. 라운드 넘버로 확정
# (분포를 보고 고른 값이 아니다 — 그러면 그 자체가 스누핑이다).
THETA_GRID = (0.03, 0.10)

# 보유기간(거래일) — 문헌의 단기(1주)/표준(1개월 상당) 창.
H_GRID = (5, 20)

# 손절 배수(ATR14% 대비) — GDR(0.75~1.5)보다 넓게: 다일 보유라 단기
# 노이즈에 덜 민감해야 한다는 기획안 §3의 판단을 그대로 승계.
K_STOP_GRID = (1.5, 2.5)

PREREGISTERED_GRID = [
    (theta, h, k_stop) for theta in THETA_GRID for h in H_GRID for k_stop in K_STOP_GRID
]
assert len(PREREGISTERED_GRID) == 8, "격자 크기는 사전등록된 8칸이어야 한다"

# ---------------------------------------------------------------------------
# 제외 조건
# ---------------------------------------------------------------------------
# 배당락 제외창 — GDR C5(gap_rebound.py EX_DIV_WINDOW) 그대로 승계.
# pykrx 일봉이 현금배당 미조정이라는 기존 한계(README 기존 한계와 동일)가
# 다일 보유(H거래일) 구간 동안의 손절/시간청산 가격에도 왜곡을 줄 수
# 있다 — GDR과 동일한 12/22~12/31 윈도우로 진입일 기준 제외한다. 보유
# 구간 전체가 아니라 진입일 기준만 보는 건 GDR과 동일 수준의 보수화이고,
# 더 정교한 처리(보유구간 전체 스캔)는 실제 신호 함수 구현(Phase 3)에서
# 필요성이 확인되면 추가한다 — 지금은 과설계하지 않는다.
EX_DIV_WINDOW = ("1222", "1231")

# 롱온리 — 공매도 비용 모델(대주 수수료·상환 리스크)이 이 저장소에 없어
# 음(-) 서프라이즈 쪽은 애초에 검증 대상에서 제외(기획안 §1.3, 결과
# 보고 나서 뺀 게 아니라 사전 배제).
LONG_ONLY = True

# ---------------------------------------------------------------------------
# 최소 표본 문턱 (기획안 §7·§8, Phase 1 실측 반영 — 수익률 보기 전 확정)
# ---------------------------------------------------------------------------
# Phase 1 실측: 95종목 corp_code 매핑 95/95, 원시 잠정실적 이벤트 4,906건
# (정정공시 포함, 최초접수분 중복제거 전). 정정공시 제거·원본결측 제외
# (README "PEAD Phase 1 데이터 스파이크 실행" §10) 후에도 초안 문턱
# (300건/150일)에 넉넉한 여유가 있을 것으로 판단해 그대로 확정한다.
MIN_EVENTS = 300
MIN_DISTINCT_DATES = 150

# ---------------------------------------------------------------------------
# 판정 규칙 (기획안 §7)
# ---------------------------------------------------------------------------
# 8칸 전 칸의 E_net(costs.yaml Base 비용 차감 순기대값) 부호 + 이동블록
# 부트스트랩 95% CI(블록 길이 in {H, 1.5H, 2H})를 전수 보고한다. 최선
# 칸만 골라 채택하지 않는다 — 기존 GDR/VCB-Gap 관례와 동일.
#
# 사전등록 반증 가능 예측(falsifiable prediction, GDR-V의 "v_mult
# 용량-반응"과 같은 역할): SUE 임계 θ가 클수록(서프라이즈가 클수록)
# E_net이 좋아야 한다(단조성). 이게 깨지면 서프라이즈 정보가 드리프트를
# 설명하지 못한다는 반증이다 — Phase 3 보고에서 이 단조성 성립 여부를
# 별도로 명시한다.
MONOTONICITY_PREDICTION = (
    "theta가 클수록(서프라이즈가 클수록) E_net(비용 차감 순기대값)이 "
    "개선되어야 한다 — 8칸 결과 보고 시 이 단조성 성립 여부를 별도 명시."
)


# ---------------------------------------------------------------------------
# Phase 3 — 신호 로직 (사전등록 상수만 소비, 로직 자체는 §5 확정 이후 무변경)
# ---------------------------------------------------------------------------

def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def compute_sue(event: DartEvent) -> float | None:
    """SUE = (OP_q - OP_{q-4}) / 매출액(SUE_DENOMINATOR="sales" 확정값).

    필요한 수치 중 하나라도 원본 결측(None)이거나 매출액이 0이면 None —
    이 이벤트는 표본에서 제외한다(GDR의 insufficient_history와 동일 취급,
    README "PEAD Phase 1 데이터 스파이크 실행" §10에서 사람이 승인한
    처리 방식).
    """
    if event.op_income_current is None or event.op_income_prior_year_same_q is None:
        return None
    if event.sales_current is None or event.sales_current == 0:
        return None
    return (event.op_income_current - event.op_income_prior_year_same_q) / event.sales_current


def pead_signal(
    event: DartEvent,
    bars: list[OhlcvBar],
    entry_open: float,
    entry_date: str,
    theta: float,
    hold_days: int,
    k_stop: float,
) -> EventSignal | None:
    """PEAD 진입 신호 판정 — GDR(gap_rebound_signal)과 같은 계약 형태:
    조건 미충족이면 None, 충족하면 EventSignal.

    bars: entry_date **이전**(D-1까지)의 일봉, ATR14 계산용(시간순,
    최소 MIN_ATR_HISTORY개). entry_open: entry_date(D+1) 시가 — 호출부가
    실제 가격 데이터에서 이미 조회해 넘긴다(이 함수는 판정만, 조회 안 함
    — gap_rebound_signal의 today_open과 동일 계약).

    조건(전부 사전등록, §5):
      1. SUE 계산 가능(원본 결측 아님) 그리고 SUE >= theta (롱온리)
      2. entry_date가 배당락 제외창(EX_DIV_WINDOW)에 안 걸림
      3. ATR14 계산 가능한 이력(len(bars) >= MIN_ATR_HISTORY)
    """
    if len(bars) < MIN_ATR_HISTORY:
        return None

    if entry_date[4:8] and EX_DIV_WINDOW[0] <= entry_date[4:8] <= EX_DIV_WINDOW[1]:
        return None

    sue = compute_sue(event)
    if sue is None or sue < theta:
        return None
    if not LONG_ONLY:  # pragma: no cover — 사전등록상 항상 True, 실수 변경 방지 가드
        raise NotImplementedError("LONG_ONLY=False는 사전등록되지 않음")

    y = bars[-1]  # D(공시 접수일)의 봉 — ATR14는 D일까지의 이력으로 계산
    trs = [
        _true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])
    ]
    atr14 = sum(trs) / len(trs)
    atr_pct = atr14 / y.close

    stop = entry_open * (1 - k_stop * atr_pct)

    return EventSignal(
        ticker=event.ticker,
        entry_date=entry_date,
        entry_price=entry_open,
        stop_price=round_up_to_tick(stop),
        hold_days=hold_days,
    )
