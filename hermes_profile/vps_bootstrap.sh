#!/usr/bin/env bash
# VPS 최초 1회 보안 강화 + 필수 패키지 설치 스크립트.
#
# OnlyTerp/hermes-optimization-guide의 vps-bootstrap.sh 패턴(커뮤니티에서
# 검증된 Hetzner CX22 대상 10분 세팅)을 참고해 우리 프로젝트용으로 다시
# 작성했다 — curl/jq/git/python3-venv/ufw/fail2ban/caddy 설치, UFW로
# 22(SSH)/80·443(웹) 포트만 열고, fail2ban으로 SSH 무차별 대입 공격을
# 막는다. Hermes 공식 인스톨러 실행까지 이 스크립트가 처리한다.
#
# 대상: Ubuntu 24.04 / Debian 12 (Hetzner CX22 기본 이미지 기준). 다른
# 배포판이면 패키지 관리자 명령을 바꿔야 한다.
#
# 이 스크립트가 하지 않는 것(README.md의 이후 단계에서 수동으로): 저장소
# clone, Hermes 프로필 설치, .env 채우기, 크론 등록, Caddyfile 배치 —
# 전부 이 프로젝트(저장소 경로, 인증정보) 고유의 값이 필요해서 여기 넣지
# 않았다.
#
# 사용법(신규 VPS에서 root 또는 sudo 권한으로):
#   curl -fsSL <이 파일의 raw URL> | bash
#   또는: git clone 후 bash hermes_profile/vps_bootstrap.sh

set -euo pipefail

echo "[1/5] 패키지 목록 갱신 + 필수 패키지 설치"
sudo apt-get update -y
sudo apt-get install -y curl jq git python3 python3-venv python3-pip ufw fail2ban

echo "[2/5] Caddy 설치 (리버스 프록시 + 자동 HTTPS)"
if ! command -v caddy >/dev/null 2>&1; then
    sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -y
    sudo apt-get install -y caddy
fi

echo "[3/5] 방화벽(UFW) — SSH(22)/HTTP(80)/HTTPS(443)만 허용"
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo "[4/5] fail2ban 활성화 (SSH 무차별 대입 방어)"
sudo systemctl enable --now fail2ban

echo "[5/5] Hermes Agent 공식 인스톨러 실행"
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

cat <<'EOF'

부트스트랩 완료. 다음은 hermes_profile/README.md의 단계별 안내를 따르세요:
  3. 이 저장소 clone + pip install
  4. hermes profile install ...
  5. .env 설정(Hermes 프로필용 + 저장소 자체 .env)
  6. cron/create_cron_jobs.sh로 스케줄 등록
  7. gateway install/start
  8. 대시보드: phase0-dashboard.service(localhost:8080) + Caddyfile 배치

주의: 8080 포트는 이제 UFW에서 열려있지 않다 — 의도된 것이다. 대시보드는
Caddy가 80/443에서 받아 localhost:8080으로만 프록시한다(외부에 직접
노출되지 않음).
EOF
