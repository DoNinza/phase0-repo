#!/usr/bin/env python3
"""STAGE 3 표1~8을 원본 phase0_engine.py와 동일한 형태로 출력.

사용법: python scripts/print_tables.py
"""

from phase0.config.costs import base_breakdown, scenario_costs
from phase0.engine import tables


def main() -> None:
    bd = base_breakdown()
    print(f"Base 왕복비용: {bd.base_total * 100:.2f}% (기준일 {bd.last_verified})")
    if bd.unresolved:
        print(f"[주의] 미확정 항목: {bd.unresolved} — Phase 0 Blocker 미해소")
    print()

    print(tables.t_r01_verify()); print()
    print(tables.t_breakeven(bd.base_total)); print()
    print(tables.t_reqp(bd.base_total)); print()
    print(tables.t_cost_sens(scenario_costs())); print()
    print(tables.t_annual()); print()
    print(tables.t_target(bd.base_total)); print()
    print(tables.t_wf()); print()
    print(tables.t_streak(bd.base_total))


if __name__ == "__main__":
    main()
