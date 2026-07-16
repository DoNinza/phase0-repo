지금은 평일 장 마감 직후({{TIMEZONE}} 기준 15:37, KST)다. `{{REPO_DIR}}` 에서
`PYTHONIOENCODING=utf-8 python scripts/paper_trade_gdr.py --mode resolve`를
실행해서 오늘 기록된 GDR 페이퍼 진입들을 실제 고가/저가/종가로 해소하라.

해소된 결과(승/패, pnl%)를 짧게 보고하라 — 매번 길게 보고할 필요는 없고,
이겼는지 졌는지와 몇 건인지 한두 줄이면 충분하다. 에러나 인증정보 문제가
있으면 반드시 알려라.

만약 이번이 이번 주의 금요일 실행이었다면(주간 마지막), 이번 주 누적
페이퍼 트레이딩 결과(daily_return/weekly_return 등)를 phase0.paper.trade_log
함수로 계산해서 간단히 요약 보고하라.
