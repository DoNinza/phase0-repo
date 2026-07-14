# Phase 0 계산 엔진 저장소

`자동매매_시스템_기획안_v4.md` STAGE 7의 즉시 실행계획 중 **A그룹(코드/구조 작업)**을
패키지 형태로 구현한 것. 원본 `phase0_engine.py`(단일 파일 스크립트)를 그대로
유지하되, CI로 자동 검증되는 패키지 구조로 재편했다.

## 구조와 기획안 대응관계

| 경로 | 기획안 근거 | 내용 |
|---|---|---|
| `phase0/engine/core.py` | STAGE 3 핵심 수식 | 원본 수식 그대로. 하드코딩 없음 |
| `phase0/engine/tables.py` | STAGE 3 표1~8 | 표 생성 — costs.yaml에서 비용을 주입받음 |
| `phase0/config/costs.yaml` | §5.5 비용 구성 분해 | 태그별(확인된 사실/외부 확인 필요 등) 비용 파라미터 |
| `phase0/config/costs.py` | §5.5 "하드코딩 금지" | costs.yaml 로더 + 시나리오별 비용 계산 |
| `phase0/bootstrap/cluster_bootstrap.py` | §5.7 (R-08) | 거래일 클러스터 통합 부트스트랩 |
| `phase0/backtest/g0_backtester.py` | §5.4 (R-05), STAGE 4 G0 | 낙관/보수 이중 경로 + 4분기 판정 |
| `tests/` | STAGE 3 "단위 테스트 통과 없이는 표 출력 금지" | 항등식 5·경계값 3 + 문서 수치 재현 39건 |
| `.github/workflows/ci.yml` | 위 원칙의 CI 게이트 | 매 push/PR마다 자동 실행 |

## 실행

```bash
pip install -e ".[dev]"
pytest tests/ -v --cov=phase0          # 전체 테스트 (39건)
python scripts/print_tables.py         # 문서 STAGE 3 표1~8 재출력
```

## 원본과 다른 점 (의도적 변경, 수치 아님)

- `t_annual()`은 이제 하드코딩된 4개 시나리오만 받지만, 원본과 완전히 동일한
  출력을 낸다 — 구조만 재편.
- **미세 발견 1건**: 원본 `t_cost_sens`는 Conservative 비용을 `.0047`로
  하드코딩했는데, 이는 `Base(0.36%) × 1.3 = 0.468%`를 표시 단계에서 반올림한
  값(0.47%)을 계산에 재사용한 것이다. 반올림 없이 그대로 계산하면 `E_trade =
  -0.048%`이며, 원본 표기(`-0.050%`)와 0.002%p 차이가 난다. 판정 방향에는
  영향 없음(둘 다 음수 → Conservative 미통과는 동일)이지만, 이 자체가
  기획안이 R-12에서 지적한 "표시값을 다시 계산에 흘려 넣는" 패턴의 축소판이라
  일부러 남겨두고 테스트로 고정했다(`tests/test_tables.py`).

## 아직 채워야 할 값 — Phase 0 Blocker (§5.6)

`costs.yaml`에서 `외부 확인 필요` 태그가 붙은 항목이 실측되기 전까지 Base
비용은 잠정치다. CI가 매번 아래를 자동 리포트한다(`unresolved_report`):

- `brokerage_commission_roundtrip` — 계좌 수수료율·최저수수료 확인 필요
- `exchange_fees` — 유관기관 제비용 요율 확인 필요 (현재 0으로 두고 Base 미반영 상태 명시)

이 값들이 실측되면 `costs.yaml`의 `value`만 갱신하면 되고, 코드 변경도
`t_r01_verify`처럼 하드코딩된 예시(원표 조건 C=0.3% 고정)를 제외한 모든 표가
자동으로 갱신된다.

## 아직 코드가 아닌 것 (STAGE 7 B·C그룹 — 사용자 조치 필요)

- KIS 약관 자동매매 적법성 확인 (Project Blocker, §5.6) — 이 저장소의 코드
  실행 여부와 무관하게 별도로 해소되어야 한다.
- 분봉 이력 범위 실호출, 계좌 수수료율 확인 — 실제 API·계좌 접근이 필요해
  이 환경에서 대신 실행할 수 없다.
- `g0_backtester.py`와 `cluster_bootstrap.py`는 현재 테스트에서 **합성
  데이터**로만 검증됐다. 실제 일봉·분봉 데이터를 연결하는 것이 다음 단계.
