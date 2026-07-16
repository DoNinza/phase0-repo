GDR 페이퍼 트레이딩 대시보드를 갱신할 시간이다({{TIMEZONE}} 기준 09~15시
매시 12·42분, KST). `{{REPO_DIR}}` 에서
`PYTHONIOENCODING=utf-8 python scripts/generate_dashboard.py`를 실행해
`data/paper_trading/dashboard.html`을 최신 로그 상태로 재생성하라.

이 VPS 배포에서는 Claude Code의 Artifact 게시 기능이 없다 — 대신
`data/paper_trading/`를 서빙하는 정적 웹서버(hermes_profile/README.md의
설치 안내에서 systemd 서비스로 상시 실행)가 항상 최신 파일을 그대로
내려준다. 그러니 이 루틴은 스크립트 실행 결과만 확인하면 되고, 별도
"게시" 단계는 필요 없다.

별다른 변화(신규 거래, 서킷브레이커 상태 변화)가 없으면 조용히 넘어가도
되고, 있으면 한두 줄로 짧게 알려라. 에러가 나면 반드시 알려라.
