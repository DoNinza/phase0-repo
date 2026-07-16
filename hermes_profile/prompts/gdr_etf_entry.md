지금은 평일 장 시작 직후({{TIMEZONE}} 기준 09:08, KST)다. `{{REPO_DIR}}` 에서
`PYTHONIOENCODING=utf-8 python scripts/paper_trade_etf_gdr.py --mode entry --universe expanded`를
실행해 오늘의 ETF GDR 페이퍼 진입 신호를 기록해라. 서킷브레이커가 발동
중이면 스크립트가 알아서 건너뛴다.

실행 결과(진입 건수, 오류 여부)만 간단히 보고하고 별도 확인은 필요 없다.
에러나 인증정보 문제가 있으면 반드시 알려라.

주의: 이 스크립트는 실주문을 절대 내지 않는다 — KIS 시세 조회(읽기 전용)만
사용해 가상 체결을 로그 파일에 기록할 뿐이다.
