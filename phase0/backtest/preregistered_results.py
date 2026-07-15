"""B7 백테스트 탭용 사전 등록(pre-registered) 결과 정적 데이터.

이 모듈은 계산을 하지 않는다 — README.md에 이미 실행·보고된 사전 등록 격자
백테스트 결과를 그대로 옮겨 적은(transcribe) 것뿐이다. 모든 수치는 README.md
원문에서 반올림·재계산·근사 없이 그대로 복사했다. 판정(verdict) 문자열도
"reject"/"insufficient_sample" 등 README가 쓴 그대로이며, 더 부드럽게
바꿔 쓰지 않는다(이 프로젝트의 정직한 보고 원칙).

각 ResultSet의 `source`에 README의 절 제목을 적어 모든 숫자를 원문까지
추적할 수 있게 했다. 여러 차례 재실행된 실험(예: GDR을 20종목 → 95종목 →
ETF 43종목 → ETF 59종목으로 재검증)은 각 라운드를 별도 ResultSet으로
남겨 두었다 — 최신/최대 유니버스 결과가 해당 전략의 "최종" 결론이지만,
더 작은 유니버스의 결과가 최종 결론과 다르게 뒤집힌 경우(GDR-V 용량-반응
패턴, VBP 유일 양수 칸)가 이 프로젝트의 핵심 발견 중 하나라 지우지 않고
같이 남긴다(README "유니버스 확장(20→95종목)" 절 참고).

주의(수치 정확성 관련): ETF 43종목 표(ETF_43)의 VCB-Gap 행에 있는
"개별주식(-0.13%)보다 오히려 나쁨"이라는 README 원문 주석은 README를
그대로 옮긴 것이다 — 이 -0.13%라는 값은 KOSPI 95종목 개별주식 VCB-Gap
결과(-0.667%, 아래 UNIVERSE_95_SUMMARY 참고)와 일치하지 않고, 오히려
미국 112종목 재검증 결과(-0.13%~-0.16%, README "미국 유니버스 확장"
절)에 더 가까운 값이다. README 자체에 어느 쪽을 가리키는지 명시가 없어
이 모듈에서 임의로 정정하거나 다른 숫자로 바꾸지 않고 원문 그대로 옮긴다
— 대신 여기 주석으로 그 모호함을 정직하게 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultRow:
    """사전 등록 격자의 한 행(조합 하나). 값은 전부 README 원문 그대로의 문자열.

    cells: `ResultSet.columns`와 1:1 대응하는, 판정을 제외한 값들.
    verdict: README가 그 행에 내린 판정 문자열 그대로(reject/insufficient_sample 등).
             표 전체에 개별 판정이 없고 서술형 결론만 있는 경우 빈 문자열.
    verdict_detail: README가 판정 뒤에 괄호 등으로 덧붙인 부가 설명(있는 그대로).
    best: README 원문에서 그 행의 대표값이 **굵게** 강조돼 있었는지(그 표 안에서
          "최선" 조합으로 표시된 셀) — 여기서 새로 판단한 게 아니라 원문 서식을
          그대로 옮긴 것이다.
    """

    cells: tuple[str, ...]
    verdict: str = ""
    verdict_detail: str = ""
    best: bool = False


@dataclass(frozen=True)
class ResultSet:
    """전략 하나 · 실험 라운드 하나에 대응하는 사전 등록 결과 표 + 맥락."""

    key: str
    title: str
    strategy: str
    universe: str
    period: str
    columns: tuple[str, ...]
    rows: tuple[ResultRow, ...]
    conclusion: str
    source: str
    date: str
    incomplete_note: str = ""


# ---------------------------------------------------------------------------
# 1) VCB-Gap — 첫 전략, KOSPI 20종목 사전 등록 6조합(§ 첫 전략 VCB-Gap ...)
# ---------------------------------------------------------------------------
VCB_GAP_20 = ResultSet(
    key="vcb_gap_20",
    title="VCB-Gap — KOSPI 20종목 사전등록 격자",
    strategy="VCB-Gap",
    universe="KOSPI 20종목 (DEFAULT_CANDIDATES)",
    period="2016-07~2026-07",
    columns=("k_target", "k_stop", "신호수", "E_conservative", "E_optimistic"),
    rows=(
        ResultRow(("1.2", "0.75", "685", "−0.638%", "−0.633%"), "insufficient_sample"),
        ResultRow(("1.2", "1.00", "685", "−0.608%", "−0.613%"), "insufficient_sample"),
        ResultRow(("1.5", "0.75", "685", "−0.619%", "−0.619%"), "insufficient_sample"),
        ResultRow(("1.5", "1.00", "685", "−0.590%", "−0.597%"), "insufficient_sample"),
        ResultRow(("2.0", "0.75", "685", "−0.602%", "−0.598%"), "insufficient_sample"),
        ResultRow(("2.0", "1.00", "685", "−0.577%", "−0.577%"), "insufficient_sample"),
    ),
    conclusion=(
        "6개 조합 전부 낙관·보수 경로 모두 마이너스로 일관됨. 표본(685건)이 G0 "
        "기준(1,000건)에 못 미쳐 형식적 판정은 표본 부족이지만, 부호가 모든 "
        "조합·양쪽 경로에서 한결같이 음수라 이 진입 규칙 자체가 KOSPI 대형주·"
        "2016~2026 구간에서 비용을 넘는 엣지를 보여주지 못했다는 것이 "
        "가장 정직한 해석이다."
    ),
    source="README.md § 첫 전략 VCB-Gap + G0 실데이터 백테스트 (STAGE 7 항목 9·10)",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 2) GDR(갭하락 반등) — KOSPI 20종목 사전 등록 6조합(§ 두 번째 전략 GDR ...)
# ---------------------------------------------------------------------------
GDR_20 = ResultSet(
    key="gdr_20",
    title="GDR(Gap-Down Rebound) — KOSPI 20종목 사전등록 격자",
    strategy="GDR",
    universe="KOSPI 20종목 (DEFAULT_CANDIDATES)",
    period="2016-07~2026-07",
    columns=("f_fill", "k_stop", "신호수", "E_conservative", "E_optimistic"),
    rows=(
        ResultRow(("0.6", "1.0", "582", "−0.253%", "−0.282%"), "insufficient_sample"),
        ResultRow(("0.6", "1.5", "582", "−0.288%", "−0.292%"), "insufficient_sample"),
        ResultRow(("0.8", "1.0", "582", "−0.187%", "−0.201%"), "insufficient_sample", best=True),
        ResultRow(("0.8", "1.5", "582", "−0.244%", "−0.247%"), "insufficient_sample"),
        ResultRow(("1.0", "1.0", "582", "−0.218%", "−0.227%"), "insufficient_sample"),
        ResultRow(("1.0", "1.5", "582", "−0.281%", "−0.284%"), "insufficient_sample"),
    ),
    conclusion=(
        "여전히 6개 조합 전부 마이너스라 판정을 뒤집지는 못했다. 다만 최선 "
        "조합(f_fill=0.8, k_stop=1.0)의 −0.187%는 '엣지 없음' 중립 기준선"
        "(−0.385%)보다 낫다 — VCB-Gap과 달리 조건화가 손실을 줄이는 방향으로 "
        "작동했다. 표본 582건도 G0 기준(1,000건) 미달."
    ),
    source="README.md § 두 번째 전략 GDR(갭하락 반등)",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 3) GDR-V(거래량 확인 추가) — KOSPI 20종목 사전 등록 12조합
#    (§ 세 번째·네 번째 실험: GDR-V·VBP)
#    주의: 95종목 재검증(UNIVERSE_95_SUMMARY)에서 "v_mult가 클수록 낫다"는
#    이 표의 용량-반응 패턴이 6쌍 전부 정반대로 뒤집혔다 — README는 이를
#    작은 표본의 노이즈였다고 결론짓는다. 이 표는 그 노이즈였던 최초 관측을
#    그대로 보존한 것이다(지우지 않음).
# ---------------------------------------------------------------------------
GDR_V_20 = ResultSet(
    key="gdr_v_20",
    title="GDR-V(거래량 확인) — KOSPI 20종목 사전등록 격자",
    strategy="GDR-V",
    universe="KOSPI 20종목 (DEFAULT_CANDIDATES)",
    period="2016-07~2026-07",
    columns=("f_fill", "k_stop", "v_mult", "신호수", "E_conservative"),
    rows=(
        ResultRow(("0.6", "1.0", "1.2", "173", "−0.364%"), "insufficient_sample"),
        ResultRow(("0.6", "1.0", "1.5", "89", "−0.247%"), "insufficient_sample"),
        ResultRow(("0.6", "1.5", "1.2", "173", "−0.433%"), "insufficient_sample"),
        ResultRow(("0.6", "1.5", "1.5", "89", "−0.165%"), "insufficient_sample"),
        ResultRow(("0.8", "1.0", "1.2", "173", "−0.256%"), "insufficient_sample"),
        ResultRow(("0.8", "1.0", "1.5", "89", "−0.129%"), "insufficient_sample"),
        ResultRow(("0.8", "1.5", "1.2", "173", "−0.384%"), "insufficient_sample"),
        ResultRow(("0.8", "1.5", "1.5", "89", "−0.164%"), "insufficient_sample"),
        ResultRow(("1.0", "1.0", "1.2", "173", "−0.207%"), "insufficient_sample"),
        ResultRow(("1.0", "1.0", "1.5", "89", "−0.016%"), "insufficient_sample", best=True),
        ResultRow(("1.0", "1.5", "1.2", "173", "−0.334%"), "insufficient_sample"),
        ResultRow(("1.0", "1.5", "1.5", "89", "−0.049%"), "insufficient_sample"),
    ),
    conclusion=(
        "12칸 전부 여전히 마이너스. 다만 사전등록한 반증가능 예측(v_mult이 "
        "클수록 나아야 한다)이 6쌍 전부에서 예외 없이 성립했다 — 최선 조합"
        "(f_fill=1.0, k_stop=1.0, v_mult=1.5)은 −0.016%로 0에 근접. 신호 수는 "
        "GDR(582건) 대비 크게 줄었다(89~173건). [주의] 이 용량-반응 패턴은 "
        "95종목 재검증에서 6쌍 전부 정반대로 뒤집혔다 — README는 20종목 "
        "표본의 노이즈였다고 결론짓는다."
    ),
    source="README.md § 세 번째·네 번째 실험: GDR-V·VBP",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 4) VBP(Volume-anchored Breakout Pullback) — KOSPI 20종목 사전 등록 6조합
#    주의: 이 표의 유일한 양수 칸(f_ret=0.50, k_stop=1.25, +0.061%)은 43종목
#    ETF 확장이 아니라 95종목 KR 개별주식 재검증(README "유니버스 확장"
#    절)에서 −0.1147%로 반전됐다 — 아래 UNIVERSE_95_SUMMARY 참고.
# ---------------------------------------------------------------------------
VBP_20 = ResultSet(
    key="vbp_20",
    title="VBP(Volume-anchored Breakout Pullback) — KOSPI 20종목 사전등록 격자",
    strategy="VBP",
    universe="KOSPI 20종목 (DEFAULT_CANDIDATES)",
    period="2016-07~2026-07",
    columns=("f_ret", "k_stop", "신호수", "E_conservative"),
    rows=(
        ResultRow(("0.50", "0.75", "121", "−0.021%"), "insufficient_sample"),
        ResultRow(("0.50", "1.25", "121", "+0.061%"), "insufficient_sample", best=True),
        ResultRow(("0.75", "0.75", "121", "−0.140%"), "insufficient_sample"),
        ResultRow(("0.75", "1.25", "121", "−0.081%"), "insufficient_sample"),
        ResultRow(("1.00", "0.75", "121", "−0.146%"), "insufficient_sample"),
        ResultRow(("1.00", "1.25", "121", "−0.087%"), "insufficient_sample"),
    ),
    conclusion=(
        "(f_ret=0.5, k_stop=1.25) 조합이 이 프로젝트 전체를 통틀어 처음으로 "
        "비용(0.3854%) 포함 순수익 기대값이 양수로 나왔다. 다만 신호 121건·"
        "거래일 112일로 G0 표본 기준(1,000건·500일)에 한참 못 미쳐 판정은 "
        "여전히 insufficient_sample — '이길 것 같다'가 아니라 '아직 판단할 "
        "수 없다'가 정확한 해석. 6칸 중 1칸만 양수, 나머지 5칸은 여전히 "
        "마이너스라는 점도 같이 봐야 한다."
    ),
    source="README.md § 세 번째·네 번째 실험: GDR-V·VBP",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 5) 유니버스 확장(20→95종목) 요약 — 네 전략 전부 재실행, KR 개별주식 기준
#    가장 크고 최신인 KR 개별주식 유니버스 결과 — VCB-Gap/GDR은 여기서
#    최초로 "표본기준 통과"한 확정 판정(reject)을 받았다. 이 표가 KR
#    개별주식에 대한 각 전략의 최종/최대 유니버스 결론이다.
# ---------------------------------------------------------------------------
UNIVERSE_95_SUMMARY = ResultSet(
    key="universe_95_summary",
    title="네 전략 종합 — KOSPI 95종목 재검증(확정 판정 최초 등장)",
    strategy="VCB-Gap / GDR / GDR-V / VBP (종합)",
    universe="KOSPI 95종목 (EXPANDED_CANDIDATES, 20→95종목 확장)",
    period="2016-07~2026-07",
    columns=("전략", "신호수", "거래일", "최선 E_cons"),
    rows=(
        ResultRow(("VCB-Gap", "2,803", "1,320", "−0.667%"), "reject", "표본기준 통과, 최초 확정 판정"),
        ResultRow(("GDR", "1,595", "558", "−0.160%"), "reject", "표본기준 통과, 최초 확정 판정"),
        ResultRow(("GDR-V", "288~489", "178~264", "−0.168%"), "insufficient_sample"),
        ResultRow(("VBP", "532", "412", "−0.115%"), "insufficient_sample"),
    ),
    conclusion=(
        "VCB-Gap과 GDR은 표본 기준(1,000건·500일)을 넘어 G0 최초의 확정 "
        "판정(reject)을 받았다 — 20종목 결과와 방향이 일관됨(VCB-Gap이 "
        "훨씬 나쁘고, GDR이 비용에 가장 가까움). 동시에 GDR-V·VBP에서 봤던 "
        "'유망해 보이던' 패턴 두 개가 재현에 실패했다: GDR-V의 용량-반응 "
        "예측이 95종목에서 6쌍 전부 정반대로 뒤집혔고, VBP의 유일한 양수 "
        "칸(+0.061%)이 −0.1147%로 반전됐다 — 작은 표본의 그럴듯한 패턴이 "
        "노이즈였음이 표본 확대로 드러난 사례. GDR이 넷 중 비용에 가장 "
        "가깝다(−0.160%)는 사실은 95종목에서도 유지됐다."
    ),
    source="README.md § 유니버스 확장(20→95종목) — 표본 부족 문제에 대한 정직한 반전",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 6) GDR 부트스트랩 신뢰구간 — 이동 블록 부트스트랩(scripts/run_gdr_bootstrap.py)
#    [불완전 표기, 의도적] README 본문은 "사전 등록 6개 조합 × 블록길이
#    3가지 = 18개 전부 95% 신뢰구간이 0을 완전히 배제(전부 음수 구간)"라고
#    서술하지만, 18개 조합 각각의 정확한 점추정·CI를 표로 나열하지는
#    않는다 — 본문에 예시로 제시된 f_fill=1.0/k_stop=1.0/block=15 조합 단
#    하나만 정확한 수치가 있다. 나머지 17개 조합의 개별 수치는 README에
#    없으므로 이 모듈에서 추정해 채우지 않는다(데이터마이닝 방지 원칙과
#    동일한 이유로, 없는 걸 있는 것처럼 보고하지 않는다).
# ---------------------------------------------------------------------------
GDR_BOOTSTRAP_CI = ResultSet(
    key="gdr_bootstrap_ci",
    title="GDR 부트스트랩 95% 신뢰구간 (이동 블록, 95종목)",
    strategy="GDR",
    universe="KOSPI 95종목 (EXPANDED_CANDIDATES)",
    period="2016-07~2026-07",
    columns=("f_fill", "k_stop", "block_length", "점추정 net E_trade", "95% CI"),
    rows=(
        ResultRow(("1.0", "1.0", "15", "−0.176%", "[−0.336%, −0.003%]"), "reject",
                   "95% CI가 0을 완전히 배제 (1,000회 재표본)"),
    ),
    conclusion=(
        "사전 등록 6개 조합 × 블록길이(10/15/20일) 3가지 = 18개 전부 95% "
        "신뢰구간이 0을 완전히 배제했다(전부 음수 구간). 블록 길이를 "
        "10/15/20으로 바꿔도 결론이 흔들리지 않았다 — GDR의 기각은 이제 "
        "'표본이 적어 아직 모른다'가 아니라 '표본이 충분하고, 신뢰구간이 "
        "통계적으로 0을 배제한다'로 격상됐다."
    ),
    source="README.md § GDR 부트스트랩 신뢰구간 (scripts/run_gdr_bootstrap.py)",
    date="2026-07-15",
    incomplete_note=(
        "일부 조합만 표기 — README 원문에는 18개 조합 중 이 1개(f_fill=1.0/"
        "k_stop=1.0/block=15)의 점추정·CI만 예시로 제시돼 있고, 나머지 17개는 "
        "'전부 0을 배제'라는 정성적 결론만 확인 가능. 원본 README 참고."
    ),
)


# ---------------------------------------------------------------------------
# 7) GDR ML 스마트 필터 — 로지스틱 회귀, 시간순 80/20 분할 OOS
# ---------------------------------------------------------------------------
GDR_ML_FILTER_OOS = ResultSet(
    key="gdr_ml_filter_oos",
    title="GDR ML 스마트 필터 — OOS 성과 비교",
    strategy="GDR + ML 필터(로지스틱 회귀)",
    universe="KOSPI 95종목 GDR 신호(f_fill=1.0/k_stop=1.0), 시간순 80/20 분할(2024-06-27 이후 OOS)",
    period="OOS: 2024-06-27~2026-07",
    columns=("구분", "신호수", "승률", "E_trade(OOS)"),
    rows=(
        ResultRow(("필터 없음(원 GDR)", "373", "51.47%", "−0.4260%")),
        ResultRow(("ML 필터(P(win)≥0.5)", "184", "49.46%", "−0.4797%")),
    ),
    conclusion=(
        "ML 필터는 도움이 안 됐다 — 신호를 절반으로 줄였는데도 승률이 "
        "오히려 떨어졌다(51.47%→49.46%), 학습 구간 IS 승률(56.46%)이 OOS에서 "
        "재현되지 않은 전형적 과적합 징후. 더 중요한 발견: 필터와 무관하게 "
        "OOS 구간의 원 GDR E_trade(−0.426%)가 10년 전체 평균(−0.160%)보다 "
        "뚜렷이 나쁘다 — 시장 체제 변화(regime change) 가능성을 시사한다. "
        "이로써 규칙 기반 4개 + ML 필터 1개, 총 5개 접근법이 전부 실패했다."
    ),
    source="README.md § GDR ML 스마트 필터 (scripts/train_gdr_ml_filter.py)",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 8) ETF 비용구조 재검증 — 1차: 43개 ETF(15→43종목 확장)
# ---------------------------------------------------------------------------
ETF_COST_RETEST_43 = ResultSet(
    key="etf_cost_retest_43",
    title="ETF 비용구조 재검증 — 43개 ETF (1차 확장)",
    strategy="VCB-Gap / GDR / GDR-V / VBP (종합)",
    universe="43개 국내 주식형 ETF (코스피200 추종 6종 + 섹터 9종 + 확장 28종, etf_candidates.py)",
    period="2016~2026",
    columns=("전략", "최선 E_cons"),
    rows=(
        ResultRow(("VCB-Gap", "−0.295%"), "reject",
                   "1,925신호·810일, 표본충분 — 개별주식(−0.13%)보다 오히려 나쁨"),
        ResultRow(("GDR", "−0.110%"), "insufficient_sample",
                   "2,031신호·418일, 500일 문턱 근소 미달 — 지금까지 중 가장 0에 근접"),
        ResultRow(("GDR-V", "−0.030%"), "insufficient_sample",
                   "574신호·205일 — 역대 최고 근접치", best=True),
        ResultRow(("VBP", "−0.255%"), "insufficient_sample", "173신호·138일"),
    ),
    conclusion=(
        "국내 주식형 ETF는 매도 시 거래세+농특세(0.20%)가 면제되고 매매차익도 "
        "비과세라 Base 비용이 0.3854%→약 0.1854%로 거의 절반이 된다. 비용 "
        "구조를 바꾼 것이 새 가설을 만드는 것보다 실제로 더 유의미한 개선을 "
        "만들어냈다 — GDR/GDR-V가 이 프로젝트 전체를 통틀어 가장 0에 가까운 "
        "결과를 냈다. 다만 15→43종목 확장에서 VBP는 양수 4개 칸(+0.06~"
        "+0.13%, 15종목 기준)이 전부 마이너스로 뒤집혔다 — 작은 표본의 유망한 "
        "패턴이 큰 표본에서 소멸한 또 다른 사례. 아직 통과가 아니라 "
        "표본부족이다."
    ),
    source="README.md § 논점 전환: ETF 비용구조 — 여섯 번의 실패 뒤 비용 자체를 다루다",
    date="2026-07-15",
)


# ---------------------------------------------------------------------------
# 9) ETF 비용구조 재검증 — 2차: 43→59종목 재확장 (최신/최종 ETF 유니버스)
# ---------------------------------------------------------------------------
ETF_COST_RETEST_59 = ResultSet(
    key="etf_cost_retest_59",
    title="ETF 비용구조 재검증 — 59개 ETF (2차 재확장, 최신)",
    strategy="VCB-Gap / GDR / GDR-V / VBP (종합)",
    universe="59개 국내 주식형 ETF (43→59종목 재확장, EXPANDED_CANDIDATES)",
    period="2016~2026",
    columns=("전략", "최선 E_cons (43→59)"),
    rows=(
        ResultRow(("VCB-Gap", "−0.295%→−0.276%"), "reject", "2,578신호·890일, 표본충분"),
        ResultRow(("GDR", "−0.110%→−0.092%"), "insufficient_sample", "2,794신호·494일"),
        ResultRow(("GDR-V", "−0.030%→−0.017%"), "insufficient_sample",
                   "776신호·238일 — 역대 최고 근접치 갱신", best=True),
        ResultRow(("VBP", "−0.255%→−0.270%"), "insufficient_sample",
                   "225신호·162일 — 재역전 없음"),
    ),
    conclusion=(
        "43→59종목 재확장에서 VBP는 이전처럼 뒤집히지 않고 마이너스 방향 "
        "그대로 유지됐다 — 15→43 구간의 '+에서 −로 반전'은 진짜 표본 "
        "노이즈가 해소된 것이었고, 43→59는 이미 안정된 결과를 재확인한 "
        "것으로 해석된다. GDR/GDR-V는 이번에도 방향이 안 바뀌고 계속 0에 "
        "더 가까워졌다 — 15→43→59 세 구간 연속으로 같은 방향인 건 우연이라기엔 "
        "패턴이 뚜렷하지만, 셋 다 여전히 insufficient_sample이라 사전등록 격자 "
        "백테스트만으로는 확정 판정을 못 낸다. ETF 유니버스는 국내 비레버리지·"
        "비인버스 주식형 상품 대부분을 이미 포함해 추가 확장의 한계 수익이 "
        "낮다 — 다음 표본 확대는 유니버스가 아니라 시간(페이퍼 트레이딩)에서 "
        "나와야 한다."
    ),
    source="README.md § 43종목→59종목 재확장 — 방향 재확인, 여전히 표본부족",
    date="2026-07-16",
)


# 대시보드가 렌더링 순서대로 순회할 전체 목록. 실험이 진행된 시간순(README
# 등장 순서)으로 나열 — 나중 실험이 앞선 실험의 결과를 대체하는 게 아니라
# 별도 유니버스/비용구조에서의 재검증이므로 전부 유지한다.
ALL_RESULT_SETS: tuple[ResultSet, ...] = (
    VCB_GAP_20,
    GDR_20,
    GDR_V_20,
    VBP_20,
    UNIVERSE_95_SUMMARY,
    GDR_BOOTSTRAP_CI,
    GDR_ML_FILTER_OOS,
    ETF_COST_RETEST_43,
    ETF_COST_RETEST_59,
)
