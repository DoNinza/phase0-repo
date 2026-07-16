지금은 평일 장 시작 직후({{TIMEZONE}} 기준 09:06, KST)다. `{{REPO_DIR}}` 에서
`PYTHONIOENCODING=utf-8 python scripts/paper_trade_gdr.py --mode entry --universe expanded`를
실행해서 오늘의 GDR 페이퍼 트레이딩 진입을 기록하라.

서킷브레이커가 발동됐다는 메시지가 나오면 그 사유를 짧게 보고하라. 신호가
발생했으면 몇 건인지만 짧게 보고하고, 별다른 문제 없으면 조용히 넘어가도
된다(매번 긴 보고 불필요) — 다만 에러가 나거나 인증정보 문제(KIS_APP_KEY,
KIS_ENV 등)가 있으면 반드시 알려라.

주의: 이 스크립트는 실주문을 절대 내지 않는다 — KIS 시세 조회(읽기 전용)만
사용해 가상 체결을 로그 파일에 기록할 뿐이다.
