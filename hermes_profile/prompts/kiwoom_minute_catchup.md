평일 장 마감 직후({{TIMEZONE}} 기준 15:41, KST)다. `{{REPO_DIR}}` 에서
`PYTHONIOENCODING=utf-8 python scripts/collect_minute_bars_kiwoom.py --max-calls 3`를
실행해 오늘 포함 최근 며칠치 5분봉을 캐치업하라(append_bars가 중복은
자동 제외하므로 안전).

종목별 결과를 짧게 요약 보고하고, 실패하거나 봉 개수가 비정상적인 종목이
있으면 알려라. 에러나 인증정보 문제(특히 KIWOOM_ENV 불일치, 토큰 발급
실패)가 있으면 반드시 알려라.

배경: 예전엔 KIS 분봉 API(collect_minute_bars.py, 당일치만·호출당 30봉)를
썼는데, 실거래일 실측에서 KIS가 반복적으로 500 에러를 내고 키움은
호출당 900봉으로 훨씬 안정적인 게 확인돼 이 루틴으로 완전히 대체했다.
