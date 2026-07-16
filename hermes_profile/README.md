# Phase 0 Hermes 프로필 — VPS 상시 배포용

## 이게 뭔가

지금까지 이 프로젝트의 자동매매 크론 9개(진입/청산/분봉·일봉·지수 수집/
대시보드 갱신)는 Claude Code 대화 세션 안에서만 사는 임시 스케줄러
(CronCreate)로 돌아갔다 — 최대 7일 뒤 자동 만료되고, 세션이 끊기면
그 즉시 사라진다. 이 폴더는 그 크론들을 **VPS에서 영구적으로** 돌리기
위해 [Hermes Agent](https://github.com/NousResearch/hermes-agent)(Nous
Research의 오픈소스 자율 에이전트 프레임워크) 위에 얹는 "프로필"이다.

Hermes를 고른 이유: 순수 리눅스 crontab(무인 실행)과 달리, 지금 우리가
누리는 "에러 나면 재시도해보고, 이상하면 사람 말로 보고하는" 판단
레이어를 유지할 수 있다 — 각 루틴이 Claude(또는 다른 LLM)에게 자연어
프롬프트로 전달되고, 그 판단 하에 스크립트를 실행한다.

**정직하게 남기는 한계**: 이 프로필은 아직 실제 VPS+Hermes 환경에서
설치·검증된 적이 없다(개발 환경이 Windows라 Hermes를 직접 못 돌려봄).
GitHub 공식 문서와 실제 배포된 참고 사례(아래)의 문법을 최대한 정확히
베꼈지만, `hermes cron create` 같은 정확한 CLI 옵션은 실제 설치 후
`hermes cron --help`로 재확인해야 한다.

## 참고한 실제 사례

[`tradermonty/hermes-trading-research-agent-work-package`](https://github.com/tradermonty/hermes-trading-research-agent-work-package) —
미국 주식 트레이더용 "상시 리서치·저널링 보조" Hermes 프로필. **"No order
placement"** 원칙이 이 프로젝트의 Phase 0 원칙과 동일해 구조(디렉터리
레이아웃, `cron/create_cron_jobs.py`가 `<profile> cron create`를 호출하는
방식)를 그대로 참고했다. 다만 그쪽은 미국장(FMP/FINVIZ/Alpaca)용이라
그대로 쓸 수는 없어 우리 KIS/키움 스크립트에 맞게 새로 작성했다.

## 디렉터리 구조

```
hermes_profile/
├── vps_bootstrap.sh              # VPS 최초 1회: 필수 패키지+Caddy+UFW+fail2ban+Hermes 설치
├── prompts/                      # 루틴별 자연어 프롬프트(기존 크론 프롬프트 그대로 이관)
├── data/schedule-presets.yaml    # 스케줄(cron 5필드) + 프롬프트 파일 매핑
├── cron/create_cron_jobs.py      # schedule-presets.yaml을 읽어 실제 등록
├── dashboard_server/             # 대시보드용 정적 파일 서버(systemd) + Caddy 리버스 프록시
└── .env.EXAMPLE                  # Hermes 프로필용 인증정보 템플릿
```

## 설치 절차

### 0. VPS 업체/스펙 추천

GitHub 커뮤니티 사례(`OnlyTerp/hermes-optimization-guide` 등) 기준으로
**Hetzner**가 Hermes 호스팅용으로 사실상 만장일치 추천을 받는다 — 같은
스펙 기준 DigitalOcean/AWS Lightsail보다 가격 대비 성능이 확실히 좋다.

- **추천**: Hetzner **CX22**(2 vCPU, 4GB RAM, 40GB NVMe) — 월 약 $4,
  Ubuntu 24.04 이미지 선택. (아시아 리전이 필요하면 Vultr/DigitalOcean
  서울 리전, 또는 네이버클라우드도 대안 — 다만 커뮤니티 검증 사례는
  Hetzner 쪽이 훨씬 많다.)
- 우리 워크로드(브라우저 자동화 없이 짧은 파이썬 스크립트만 정기 실행)는
  가벼운 축이라 최소 스펙(1GB RAM)으로도 충분할 가능성이 높지만, 여유를
  두려면 CX22 권장.

### 1. VPS 최초 부트스트랩 (보안 강화 + 필수 패키지 + Hermes 설치)

`vps_bootstrap.sh`가 `OnlyTerp/hermes-optimization-guide`의 검증된 패턴을
따라 한 번에 처리한다: curl/git/python3-venv 등 필수 패키지, **Caddy**
(리버스 프록시+자동 HTTPS), **UFW**(22/80/443만 허용), **fail2ban**(SSH
무차별 대입 방어), 마지막으로 Hermes 공식 인스톨러까지.

```bash
# 신규 VPS에 SSH 접속한 뒤
git clone <이 저장소 URL> /opt/phase0_repo
cd /opt/phase0_repo
bash hermes_profile/vps_bootstrap.sh
```

### 2. 저장소·의존성 확인
(부트스트랩에서 이미 clone했다면 `git clone` 줄은 건너뛴다.)
```bash
cd /opt/phase0_repo   # 없으면: git clone <이 저장소 URL> /opt/phase0_repo && cd /opt/phase0_repo
pip install -e ".[data,ml]"   # phase0 패키지 + pykrx/requests/yfinance/scikit-learn 등
pip install pyyaml            # cron/create_cron_jobs.py가 사용
```

### 3. 프로필 설치
```bash
hermes profile install "/opt/phase0_repo/hermes_profile" --name phase0-trader --alias -y
phase0-trader config set model claude-opus-4-7
phase0-trader config set provider anthropic
```

### 4. 인증정보 설정
```bash
cp hermes_profile/.env.EXAMPLE ~/.hermes/profiles/phase0-trader/.env
nano ~/.hermes/profiles/phase0-trader/.env   # 실제 값 입력
```
그리고 저장소 자체의 `.env`도 별도로 채워야 한다(스크립트들이 직접
`phase0.config.kis_credentials`/`kiwoom_credentials`로 읽음):
```bash
cp .env.example .env
nano .env
```

### 5. 스케줄 등록
```bash
export HERMES_PROFILE_CMD=phase0-trader
export HERMES_REPO_DIR=/opt/phase0_repo
bash hermes_profile/cron/create_cron_jobs.sh
phase0-trader cron list   # 9개 등록됐는지 확인
```

### 6. 게이트웨이(상시 실행) 시작
```bash
phase0-trader gateway install
phase0-trader gateway start
```

### 7. 대시보드 웹서버 (localhost) + Caddy 리버스 프록시
```bash
# 대시보드 서버는 127.0.0.1:8080에만 바인딩(외부에 직접 노출 안 함)
sudo cp hermes_profile/dashboard_server/phase0-dashboard.service /etc/systemd/system/
sudo sed -i "s|<REPO_DIR>|/opt/phase0_repo|; s|<VPS_USER>|$USER|" /etc/systemd/system/phase0-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now phase0-dashboard

# Caddy가 80/443에서 받아 위 포트로만 프록시 + 도메인 있으면 자동 HTTPS
sudo cp hermes_profile/dashboard_server/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # 도메인 있으면 example.com을 실제 도메인으로, 없으면 파일 안내대로 IP용 블록으로 교체
sudo systemctl reload caddy
```
`https://<도메인 또는 VPS IP>/dashboard.html`로 접속 확인. 도메인 없이
IP만 쓰면 자체서명 인증서 경고가 뜨는 게 정상이다(개인용 읽기전용
대시보드라 감수 가능한 수준 — Caddyfile 안의 안내 참고).

## 검증 체크리스트 (VPS에서 실제로 확인할 것)

- [ ] `hermes cron create` 문법이 문서와 일치하는지 (`hermes cron --help`)
- [ ] 각 프롬프트 파일의 `{{REPO_DIR}}`가 실제 경로로 정확히 치환됐는지
- [ ] 첫 진입 루틴(09:06)이 실제로 `paper_trade_gdr.py`를 실행하고
      `data/paper_trading/gdr_trades.jsonl`이 갱신되는지
- [ ] 대시보드 웹서버가 재부팅 후에도 자동 기동하는지(`systemctl is-enabled`)
- [ ] `sudo ufw status`로 22/80/443만 열려 있는지(8080은 닫혀 있어야 정상)
- [ ] `sudo systemctl status fail2ban`이 active인지
- [ ] KIS_ENV/KIWOOM_ENV가 의도한 값(vps/mock 또는 prod)인지 재확인 —
      Windows 개발 환경과 VPS `.env`가 다른 값일 수 있으니 복사 실수 주의
