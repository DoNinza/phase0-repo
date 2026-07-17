"""FFD(Foreign Flow Drift) 전략: 외국인 N일 누적 순매수 강도 후 단기 드리프트
(fable5 설계, 2026-07-17).

아홉 번째 가설 트랙 — 배경·데이터소스·근거는
docs/foreign_flow_nat_전략_기획안.md(Phase 1 게이트 0/(a)/(b) 실행 결과는
같은 문서 §10, README "FFD Phase 1 게이트 0 통과"/"게이트 (a)(b) 통과"
참고). 게이트 (c)(당일 데이터 공표 시점 실측)는 다음 거래일(2026-07-20)에
실행 예정이며, 기획안 §8대로 게이트 (c)와 Phase 2(본 모듈)는 독립이다.

이 모듈은 **Phase 2 산출물** — 사전등록 파라미터를 코드로 확정 커밋하는
자리다(기획안 §5 "사전등록 틀 초안" 전 항목을 이 모듈 상수로 확정, §8
로드맵 Phase 2). 이 커밋 시점까지 수익률 데이터는 이 세션에서 전혀
조회하지 않았다 — 외국인 순매수대금·거래대금의 실제 수치를 단 한 번도
보지 않은 채, 순수하게 §5의 사전 논의(데이터 가용성·기존 컨벤션·논문
근거)만으로 아래 상수를 정했다(pead.py/gap_rebound.py의 "결과 보고 조정
금지" 원칙과 동일). **이 커밋 이후 백테스트 결과를 보기 전까지 어떤
항목도 수정하지 않는다.**

명명 규약: 기획안 §3/§5는 임계값을 φ(phi)로 표기하지만, 이 저장소의
전략 모듈 명명 관례(PEAD의 THETA_GRID)와 일관되도록 코드 상수명은
THETA_GRID로 통일한다 — 의미는 기획안의 φ와 동일(외국인 순매수 강도
임계), 이름만 프로젝트 컨벤션에 맞춘 것.

Phase 3(투자자별 매매동향 수집 파이프라인 `phase0/data/investor_flow_ingest.py`,
백테스트 스크립트)는 이 커밋에 포함하지 않는다 — 게이트 (c) 완료 후 착수.
"""

from __future__ import annotations

from dataclasses import dataclass

from phase0.backtest.event_backtester import EventSignal
from phase0.data.pykrx_ingest import OhlcvBar
from phase0.strategy.vcb_gap import round_up_to_tick

MIN_ATR_HISTORY = 15  # ATR14 계산에 필요한 최소 일봉 수(pead.py/gap_rebound.py MIN_HISTORY와 같은 역할)

# ---------------------------------------------------------------------------
# 신호 분모 — 사전등록 확정, 2026-07-17
# ---------------------------------------------------------------------------
# 후보 2개(기획안 §3): (a) 투자자 테이블 자체의 전체 매수+매도 합/2,
# (b) OHLCV 거래대금. "OHLCV 거래대금"을 확정한다. 근거(PEAD가 SUE 분모를
# 매출액으로 확정한 것과 동일한 방식 — 데이터 의존성·가용성만으로 판단,
# 결과를 보고 고른 게 아니다):
#   1. (a)를 얻으려면 get_market_trading_value_by_date를 on='매수'/
#      on='매도' 각각 추가 호출해야 한다(§2.1 실측 — 이 함수의 on 인자는
#      매수/매도/순매수 중 하나만 반환, "거래대금 합계"를 직접 주는
#      옵션이 없다). 분자(외국인 순매수, on='순매수')만으로 이미 종목당
#      최대 4회 호출 중이던 게이트 0/(a)/(b) 스파이크(§10)에 2회를 더
#      얹는 것이고, 그 호출 전부가 2025-12-27 개편 이후 여전히 불안정한
#      로그인 경로(pykrx 이슈 #244, 2026-07-17 기준 미해결)를 통과해야
#      한다 — 실패 표면을 스스로 늘리는 선택이다.
#   2. (b)는 이미 ATR14·진입가·손절가 계산에 쓰는 동일 OHLCV 소스
#      (phase0.data.pykrx_ingest, 로그인 불필요 — README 확인상 이번
#      KRX 로그인 장벽의 영향을 받지 않은 유일한 계열)에서 그대로 얻는다.
#      추가 API 의존성이 0이다.
#   3. 개념적으로도 "시장 전체 유동성 대비 외국인 비중"이 이 신호의
#      정의(§3)이고, OHLCV 거래대금이 그 표준적 측정치다. 투자자 테이블
#      자체의 매수+매도 합산치가 이론적으로 같은 값이어야 하더라도, 게이트
#      (b)(§10)는 **행 수 일치**만 확인했지 **값 일치**는 확인하지 않았다
#      (예: "기타외국인" 구분 처리, NXT 분산 체결분 반영 방식이 두 소스
#      간에 다를 잔여 가능성 — §2.3 NXT 캐비앗). OHLCV 쪽이 더 오래
#      검증된 안정 경로다.
SIGNAL_DENOMINATOR = "ohlcv_total_value"  # 다른 값 사용 금지(사전등록).

# ---------------------------------------------------------------------------
# 사전등록 격자 (기획안 §5, 총 2x2x2 = 8칸) — 전수 보고, 최선 칸만 채택 금지
# ---------------------------------------------------------------------------
# 외국인 순매수 강도 진입 임계(φ, 코드명 THETA_GRID) — 라운드 넘버로 확정
# (분포를 보고 고른 값이 아니다 — PEAD θ와 동일 방침). Phase 1 실측에서
# 신호가 全無/전부로 퇴화하면 수익률을 보기 전에 라운드 넘버 내 재선정한다
# (기획안 §5 각주) — 아직 그런 재선정은 없었다.
THETA_GRID = (0.05, 0.10)

# 관측창(N)=보유기간(H, 거래일) — 기획안 §3 "N=H 구속"으로 격자 차원 하나를
# 제거했다. 이건 자유도를 공짜로 줄인 게 아니라 "N일 걸려 축적된 수급
# 정보는 비슷한 시간 척도로 실현된다"는 임의의 대칭 가정을 부과한 것이고,
# N≠H 조합(예: N=5로 짧게 관측·H=20으로 길게 보유)에 실제 엣지가 있어도
# 이 격자는 원천적으로 못 잡는다 — §3/§9.1에 명시된 한계를 그대로 승계.
H_GRID = (5, 20)

# 손절 배수(ATR14% 대비) — PEAD 승계(다일 보유용 넓은 손절, GDR의 당일청산
# 손절보다 넓어야 한다는 논리 그대로).
K_STOP_GRID = (1.5, 2.5)

PREREGISTERED_GRID = [
    (theta, h, k_stop) for theta in THETA_GRID for h in H_GRID for k_stop in K_STOP_GRID
]
assert len(PREREGISTERED_GRID) == 8, "격자 크기는 사전등록된 8칸이어야 한다"

# ---------------------------------------------------------------------------
# 제외 조건
# ---------------------------------------------------------------------------
# 배당락 제외창 — GDR C5(gap_rebound.py EX_DIV_WINDOW) 그대로 승계. pykrx
# 일봉이 현금배당 미조정이라는 기존 한계가 다일 보유(H거래일) 구간의
# 손절/시간청산 가격에도 왜곡을 줄 수 있어 GDR·PEAD와 동일한 12/22~12/31
# 윈도우로 진입일 기준 제외한다.
EX_DIV_WINDOW = ("1222", "1231")

# 롱온리 — 공매도 비용 모델이 이 저장소에 없어 음(-) 강도 쪽은 애초에
# 검증 대상에서 제외(기획안 §1.2 N3 배제, §4.1 결과 보고 나서 뺀 게 아니라
# 사전 배제). THETA_GRID가 전부 양수라는 사실 자체가 이 배제를 구현한다.
LONG_ONLY = True

# ---------------------------------------------------------------------------
# 재진입 금지 (기획안 §5·§7 "재진입 금지")
# ---------------------------------------------------------------------------
# 동일 종목을 이미 보유 중이면 그 기간 동안 새로 발동한 신호는 무시한다 —
# N일 누적 신호는 이웃한 날짜에 연쇄 발동하기 쉬워(자기상관이 PEAD보다
# 강함, §7) 재진입을 허용하면 사실상 같은 이벤트를 중복 계상하는 것과
# 같다(중첩 포지션 방지). 주의: 아래 nat_flow_signal()은 PEAD의
# pead_signal()과 동일하게 "그 날짜 하나"에 대한 상태 없는(stateless)
# 판정만 한다 — 특정 종목을 지금 보유 중인지는 여러 날짜에 걸친 포지션
# 상태라 이 함수의 관측 범위 밖이다. 이 상수는 Phase 3 백테스트 루프
# (scripts/run_nat_backtest.py, 아직 미작성)가 반드시 지켜야 할 규약을
# 코드로 문서화해 둔 것이고, 강제 자체는 그 루프의 책임이다.
NO_REENTRY_WHILE_HOLDING = True

# ---------------------------------------------------------------------------
# 최소 표본 문턱 (기획안 §5·§7·§8) — Phase 1 게이트 (a)/(b) 실측 반영, 유지
# ---------------------------------------------------------------------------
# §10 게이트 (a)/(b) 실측: 95종목 중 2016-07 소급 실질 성공 95/95(상장 전
# 22종목 제외 시 진짜 데이터 문제 0건), 최근 10거래일 결측일 비율 0.0%.
# 그러나 이 실측은 "데이터가 존재하고 빠짐없이 들어오는가"(가용성)만
# 확인했을 뿐 "R_N이 THETA_GRID를 얼마나 자주 넘는가"(신호 밀도)는 전혀
# 측정하지 않았다 — 이 세션은 실제 외국인 순매수대금·거래대금 수치를 단
# 한 번도 조회하지 않았다. 가용성과 신호 밀도는 서로 다른 축이라, 가용성이
# 좋다는 결과를 신호 밀도 문턱(표본수)을 바꾸는 근거로 쓰면 "결과를 일부
# 보고 사전등록을 조정"하는 것과 실질적으로 같아진다 — 이 저장소가 금지하는
# 바로 그 패턴이다. 따라서 초안값(PEAD와 동일 절대치)을 **그대로 유지**하고
# 조정하지 않는다. 신호가 일별이라 PEAD(분기 공시, 종목당 연 4회)보다
# 절대적으로 더 두터울 것으로 기대되지만(§7), 그 기대 자체도 Phase 3 실측
# 전까지는 추정일 뿐이다 — THETA_GRID 상단 칸(0.10, 특히 H=20의 20일
# 누적강도가 지속적으로 10%를 넘는 경우)이 얇을 위험은 §5·§9.2에서 이미
# 인정한 한계로 남아 있다. 실제로 얇으면 PEAD의 θ=0.10 전례(표본부족으로
# 부트스트랩 자체 생략)와 동일하게 그 칸만 통계 표시를 보류한다 — 문턱
# 자체를 낮추지 않는다.
MIN_EVENTS = 300
MIN_DISTINCT_DATES = 150

# ---------------------------------------------------------------------------
# 판정 규칙 (기획안 §7)
# ---------------------------------------------------------------------------
# 8칸 전 칸의 E_net(costs.yaml Base 비용 차감 순기대값) 부호 + 이동블록
# 부트스트랩 95% CI(블록 길이 in {H, 1.5H, 2H})를 전수 보고한다. 최선 칸만
# 골라 채택하지 않는다.
#
# 사전등록 반증 가능 예측(falsifiable prediction, PEAD θ 단조성과 동일 역할):
# THETA_GRID(φ)가 클수록(외국인 순매수 강도가 강할수록) E_net이 개선돼야
# 한다. PEAD에서 θ=0.10 칸이 표본부족으로 비교 자체가 성립하지 않았던
# 전례가 있으므로, φ 상단 칸이 얇아 비교 불능이면 "단조성 성립"이 아니라
# "비교 불능"으로 정직하게 표시한다(§5).
MONOTONICITY_PREDICTION = (
    "THETA_GRID(φ)가 클수록(외국인 순매수 강도가 강할수록) E_net(비용 "
    "차감 순기대값)이 개선되어야 한다 — 8칸 결과 보고 시 이 단조성 성립 "
    "여부를 별도 명시. 비교 대상 칸이 표본부족으로 하나뿐이면 '단조성 "
    "성립'이 아니라 '비교 불능'으로 표시한다(PEAD θ=0.10 전례와 동일 규율)."
)


# ---------------------------------------------------------------------------
# Phase 3 예고 — 신호 입력 데이터클래스 + 판정 함수
# (사전등록 상수만 소비, 로직 자체는 위 확정 이후 무변경)
# ---------------------------------------------------------------------------
# investor_flow_ingest.py(Phase 3, 아직 미작성)가 만들 point-in-time
# 스토어 한 행(기획안 §4.3 스키마의 부분집합)을 이 신호 함수가 바로 쓸 수
# 있는 최소 형태로 앞당겨 정의한다.


@dataclass
class DailyFlow:
    """종목 하나, 거래일 하루의 외국인 순매수·시장 거래대금 원자료.

    foreign_value_net: 외국인 순매수대금(원, `get_market_trading_value_by_date`
    on='순매수' 외국인 합계 — 외국인/기타외국인 포함 여부는 Phase 1 실측
    결과를 반영해 Phase 3 ingest 모듈에서 확정한다, 기획안 §2.1 각주).
    total_value: 같은 날의 시장 거래대금 — SIGNAL_DENOMINATOR=
    "ohlcv_total_value" 확정에 따라 이 값은 투자자 테이블이 아니라 OHLCV
    소스(OhlcvBar)에서 채워 넣어야 한다(호출부 책임).
    """

    ticker: str
    date: str  # YYYYMMDD
    foreign_value_net: float
    total_value: float


def _true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def compute_signal_strength(flows: list[DailyFlow], n: int) -> float | None:
    """R_N = 최근 n일 외국인 순매수대금 합 / 최근 n일 총거래대금 합(§3).

    flows: D일을 마지막 원소로 시간순(오름차순)으로 정렬된 리스트 — 최소
    n개 필요, 부족하면 None(GDR의 insufficient_history와 동일 취급).
    분모 합이 0이면(무거래 구간) 역시 None — 0나눗셈 방지.
    """
    if len(flows) < n:
        return None
    window = flows[-n:]
    denom = sum(f.total_value for f in window)
    if denom == 0:
        return None
    numer = sum(f.foreign_value_net for f in window)
    return numer / denom


def nat_flow_signal(
    flows: list[DailyFlow],
    bars: list[OhlcvBar],
    entry_open: float,
    entry_date: str,
    theta: float,
    h: int,
    k_stop: float,
) -> EventSignal | None:
    """FFD 진입 신호 판정 — PEAD(pead_signal)와 같은 계약 형태: 조건
    미충족이면 None, 충족하면 EventSignal. 조회는 안 하고 판정만 한다.

    flows: D일을 포함해 시간순으로 최소 h개 이상(§3 N=H 구속 — 관측창과
    보유기간이 h 하나로 묶인다). bars: entry_date **이전**(D-1까지)의
    일봉, ATR14 계산용(시간순, 최소 MIN_ATR_HISTORY개). entry_open:
    entry_date(D+1) 시가 — 호출부가 실제 가격 데이터에서 이미 조회해
    넘긴다(pead_signal의 entry_open과 동일 계약).

    조건(전부 사전등록, §5):
      1. ATR14 계산 가능한 이력(len(bars) >= MIN_ATR_HISTORY)
      2. entry_date가 배당락 제외창(EX_DIV_WINDOW)에 안 걸림
      3. R_N(=compute_signal_strength(flows, h)) 계산 가능 그리고
         R_N >= theta(롱온리)

    재진입 금지(NO_REENTRY_WHILE_HOLDING)는 이 함수의 책임이 아니다 —
    이 함수는 상태 없는 판정만 하고, 포지션 상태를 아는 Phase 3 백테스트
    루프가 강제한다(위 상수 docstring 참고).
    """
    if len(bars) < MIN_ATR_HISTORY:
        return None

    if entry_date[4:8] and EX_DIV_WINDOW[0] <= entry_date[4:8] <= EX_DIV_WINDOW[1]:
        return None

    r_n = compute_signal_strength(flows, h)
    if r_n is None or r_n < theta:
        return None
    if not LONG_ONLY:  # pragma: no cover — 사전등록상 항상 True, 실수 변경 방지 가드
        raise NotImplementedError("LONG_ONLY=False는 사전등록되지 않음")

    ticker = flows[-1].ticker
    y = bars[-1]  # D(신호 확정일)의 봉 — ATR14는 D일까지의 이력으로 계산
    trs = [
        _true_range(p.close, b.high, b.low)
        for p, b in zip(bars[-15:-1], bars[-14:])
    ]
    atr14 = sum(trs) / len(trs)
    atr_pct = atr14 / y.close

    stop = entry_open * (1 - k_stop * atr_pct)

    return EventSignal(
        ticker=ticker,
        entry_date=entry_date,
        entry_price=entry_open,
        stop_price=round_up_to_tick(stop),
        hold_days=h,
    )
