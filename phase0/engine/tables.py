"""STAGE 3 표1~8 생성 모듈.

원본 phase0_engine.py의 표 생성 함수들을 그대로 이관했다. 비용(C)은 더 이상
하드코딩하지 않고 phase0.config.costs 에서 costs.yaml을 읽어 주입한다
(기획안 STAGE 5.5: '비용·거래일수 등 입력은 설정값이며 하드코딩 금지').
"""

from __future__ import annotations

import math

from phase0.engine.core import (
    e_trade, breakeven_p, req_p, req_W, exposure, daily_account, annualize,
)

P = lambda x: f"{x * 100:.2f}%"
P1 = lambda x: f"{x * 100:.1f}%"


def t_r01_verify() -> str:
    lines = ["[표1] R-01 외부 지적 예시 검산 (원표 조건 C=0.3% 그대로)",
             "| 예시 | 조건 | v3 표기 | 외부 주장 | 엔진 검산 W=(E+(1-p)L+C)/p | 판정 |",
             "|---|---|---|---|---|---|"]
    rows = [
        ("1", "일1%/노출62.5%→E=1.6%, L=2%, C=0.3%, p=60%", "4.2%", "4.5%", req_W(.016, .60, .02, .003)),
        ("2", "동일, p=70%", "3.3%", "3.57%", req_W(.016, .70, .02, .003)),
        ("3", "일2%/노출100%→E=2.0%, L=2%, C=0.3%, p=80%", "3.6%", "3.375%", req_W(.020, .80, .02, .003)),
    ]
    for i, c, v3, ext, calc in rows:
        lines.append(f"| {i} | {c} | {v3} | {ext} | **{calc * 100:.3f}%** | v3 오류, 외부 정확 |")
    return "\n".join(lines)


def t_breakeven(C: float) -> str:
    lines = [f"[표2] 손익분기 승률 (C={P(C)})",
             "| W \\ L | 0.7% | 0.8% | 1.0% | 2.0% |",
             "|---|---|---|---|---|"]
    for W in [.010, .015, .020, .030]:
        cells = " | ".join(P1(breakeven_p(W, L, C)) for L in [.007, .008, .010, .020])
        lines.append(f"| {P1(W)} | {cells} |")
    return "\n".join(lines)


def t_reqp(C: float, E: float = .001) -> str:
    lines = [f"[표3] E_trade=+{P(E)} 필요 승률 (C={P(C)})",
             "| W (L=0.8%) | 1.2% | 1.5% | 2.0% | 2.2% |"]
    p_ = " | ".join(P1(req_p(E, W, .008, C)) for W in [.012, .015, .020, .022])
    lines.append(f"| 필요 p | {p_} |")
    return "\n".join(lines)


def t_cost_sens(scenarios: list[tuple[str, float]]) -> str:
    """scenarios: [(이름, C), ...] — phase0.config.costs.scenario_costs() 출력을 그대로 전달."""
    lines = ["[표4] 비용 민감도 (p=55%, W=1.5%, L=0.9%)",
             "| 비용 시나리오 | C | E_trade |",
             "|---|---|---|"]
    for name, C in scenarios:
        lines.append(f"| {name} | {P(C)} | {e_trade(.55, .015, .009, C) * 100:+.3f}% |")
    return "\n".join(lines)


def t_annual() -> str:
    lines = ["[표5] 연환산 — 방식 A(전체 거래일 기준 노출도, participation 중복 곱 제거)",
             "| 발동률(전체 거래일 기준) | E_trade | 노출도 | 일 기대(계좌) | 연복리(248일) | (참고) v3 구방식 |",
             "|---|---|---|---|---|---|"]
    for trig, E in [(.30, .001), (.40, .001), (.40, .0015), (.45, .003)]:
        ex = exposure(5, .125, trig)
        d = daily_account(ex, E)
        old = (1 + d) ** int(248 * .9) - 1  # v3의 중복 차감 방식(잘못) — 비교용으로만 유지
        lines.append(f"| {P1(trig)} | {P(E)} | {ex:.3f} | {d * 100:+.4f}%p | **{annualize(d) * 100:.1f}%** | {old * 100:.1f}% (과소) |")
    return "\n".join(lines)


def t_target(C: float) -> str:
    lines = [f"[표6] 일평균 1%/2% 역산 (L=2%, C={P(C)})",
             "| 목표 | 노출도 | 필요 E(net) | p=60% 필요 W | p=70% 필요 W | p=80% 필요 W |",
             "|---|---|---|---|---|---|"]
    for tgt in [.01, .02]:
        for ex in [.625, 1.0]:
            E = tgt / ex
            ws = " | ".join(f"{req_W(E, p, .02, C) * 100:.2f}%" for p in [.6, .7, .8])
            lines.append(f"| 일 {P(tgt)} | {ex:.3f} | {P(E)} | {ws} |")
    return "\n".join(lines)


def wf_segment_count(T: int, tr: int, va: int, ho: int, st: int) -> int:
    """교정 공식 (R-04): floor((T−홀드아웃−학습−검증)/스텝)+1, 음수 방지."""
    n = math.floor((T - ho - tr - va) / st) + 1
    return max(0, n)


def t_wf(T: int = 48, tr: int = 24, va: int = 6, ho: int = 6, st: int = 6) -> str:
    n = wf_segment_count(T, tr, va, ho, st)
    lines = [f"[표7] 워크포워드 구간 수 — 교정 공식 + 날짜표 (T={T}, 학습{tr}, 검증{va}, 홀드아웃{ho}, 스텝{st})",
             f"교정 공식: floor((T−홀드아웃−학습−검증)/스텝)+1 = floor(({T}−{ho}−{tr}−{va})/{st})+1 = **{n}개**",
             f"(v3 구공식 floor((T−학습−홀드아웃)/스텝)+1 = {math.floor((T - tr - ho) / st) + 1}개 → 검증기간 미차감 오류)",
             "| 구간 | 학습(월) | 검증(월) | 홀드아웃 침범? |",
             "|---|---|---|---|"]
    for i in range(n + 1):
        a, b = 1 + st * i, tr + st * i
        c, d = b + 1, b + va
        bad = "**침범→불가**" if d > T - ho else "아니오"
        mark = "" if d <= T - ho else " (제외)"
        lines.append(f"| {i + 1}{mark} | {a}~{b} | {c}~{d} | {bad} |")
    for T2 in [24, 36, 48, 60]:
        n2 = wf_segment_count(T2, tr, va, ho, st) if T2 - ho - tr - va >= 0 else 0
        lines.append(f"- T={T2}개월: 구간 {n2}개")
    return "\n".join(lines)


def t_streak(C: float) -> str:
    worst = 5 * (.0025 + C * .125)
    lines = [f"[표8] 연속 최악일 경로 (5슬롯 전부 손절, C={P(C)}): 일 −{worst * 100:.2f}%p"]
    acct = 1.0
    days10 = None
    row = []
    for day in range(1, 9):
        acct *= (1 - worst)
        row.append(f"{(acct - 1) * 100:.2f}%")
        if days10 is None and acct <= .90:
            days10 = day
    lines.append("| 일수 | " + " | ".join(str(i) for i in range(1, 9)) + " |")
    lines.append("|---|" + "---|" * 8)
    lines.append("| 누적 | " + " | ".join(row) + " |")
    lines.append(f"→ −10% 도달: 최악일 {days10}연속")
    return "\n".join(lines)
