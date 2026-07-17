"""KRX 정보데이터시스템(data.krx.co.kr) 로그인 자격증명 로더 — 외국인 수급
(FFD) 전략 트랙(`docs/foreign_flow_nat_전략_기획안.md` §2.2/§8)용.

`kis_credentials.py`/`dart_credentials.py`와 동일한 원칙: 자격증명은
코드·저장소·대화 어디에도 하드코딩하지 않고 로컬 ".env"(.gitignore 처리됨)
에서만 읽는다. 이 모듈은 그 값을 절대 출력(print/log)하지 않는다.

다른 두 로더와 성격이 다른 지점: `KIS_APP_KEY`/`DART_API_KEY`는 발급형
API 키라 이 프로젝트 코드가 값을 직접 들고 다니며 요청 파라미터에 넣지만,
`KRX_ID`/`KRX_PW`는 **웹 로그인 계정(아이디/비밀번호) 그 자체**이고
pykrx가 내부적으로 `os.environ["KRX_ID"]`/`os.environ["KRX_PW"]`를 직접
읽어 KRX 정보데이터시스템에 로그인 세션을 만든다(pykrx `website/comm/
auth.py`). 그래서 이 로더는 값을 반환하는 dataclass가 아니라, **.env를
os.environ에 주입하기만 하는** `ensure_krx_login_env()` 하나로 충분하다
— pykrx 호출부는 이 함수를 한 번 부른 뒤 평소처럼 `from pykrx import
stock`을 쓰면 된다.

주의(2026-07-17 실측, §2.2 신규 리스크): KRX 정보데이터시스템이
2025-12-27부로 회원제 "데이터 마켓플레이스"로 개편되며 네이버/카카오
간편로그인이 주 가입 방식이 됐다. 이 `KRX_ID`/`KRX_PW` 메커니즘이 그
개편된 로그인 체제와 실제로 호환되는지는 pykrx GitHub 이슈 #244(미해결)
로 남아있는 불확실성이다 — 이 모듈은 자격증명 주입만 담당하고, 실제
호환 여부는 `scripts/spike_investor_flow.py`(Phase 1 게이트 0)가 실측한다.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_KEYS = ("KRX_ID", "KRX_PW")


class CredentialsMissingError(RuntimeError):
    """.env에 KRX_ID/KRX_PW가 없을 때 발생. 실제 값은 절대 포함하지 않는다."""


def _load_dotenv_if_present(dotenv_path: Path | None = None) -> None:
    """python-dotenv가 있으면 .env를 os.environ에 로드. 없으면 조용히 넘어간다
    (사용자가 시스템 환경변수로 직접 설정했을 수도 있으므로)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = dotenv_path or Path(__file__).resolve().parents[2] / ".env"
    if path.exists():
        load_dotenv(path)


def ensure_krx_login_env() -> None:
    """.env의 KRX_ID/KRX_PW를 os.environ에 주입한다(이미 os.environ에 있으면 유지).

    pykrx는 별도의 인자 전달 경로 없이 os.environ을 직접 읽으므로, 이 함수는
    값을 반환하지 않고 부작용(os.environ 설정)만 낸다. 호출 후에도
    KRX_ID/KRX_PW가 비어 있으면 CredentialsMissingError를 던진다 —
    사용자가 아직 data.krx.co.kr 가입 전이라도 이 시점에 명확한 안내를
    받도록 하기 위함이다.
    """
    _load_dotenv_if_present()

    missing = [k for k in _ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise CredentialsMissingError(
            f"다음 환경변수가 비어 있음: {missing}. 먼저 https://data.krx.co.kr 에서 "
            "무료 회원가입을 하고, 저장소 루트의 .env.example을 .env로 복사한 뒤 "
            "KRX_ID/KRX_PW를 실제 로그인 계정(아이디/비밀번호)으로 채우고 다시 "
            "시도하세요. (2026-07-17 기준 KRX가 소셜로그인 위주로 개편됐으므로, "
            "전통 아이디/비밀번호 가입 옵션이 안 보이면 docs/"
            "foreign_flow_nat_전략_기획안.md §8 게이트 0 체크리스트를 참고하세요.)"
        )
