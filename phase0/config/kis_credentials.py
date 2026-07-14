"""KIS Open API 인증정보 로더 (STAGE 7 항목 5 실행에 필요).

원칙: APP Key/APP Secret은 계좌 비밀번호급 민감정보이므로 코드·저장소·대화
어디에도 하드코딩하지 않는다. 로컬 ".env" 파일(.gitignore 처리됨)에서만
읽는다 — costs.yaml이 비용을 하드코딩하지 않는 것과 동일한 원칙을
인증정보에 적용한 것이다.

사용법: 저장소 루트의 ".env.example"을 ".env"로 복사하고 실제 값을
채운 뒤 이 모듈을 사용한다. 이 모듈은 그 값을 절대 출력(print/log)하지
않는다 — 있는지 없는지, 몇 글자인지만 확인 가능한 형태로 다룬다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ENV_KEYS = ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "KIS_ACCOUNT_PRODUCT_CD")

_BASE_URLS = {
    "prod": "https://openapi.koreainvestment.com:9443",
    "vps": "https://openapivts.koreainvestment.com:29443",   # 모의투자
}


class CredentialsMissingError(RuntimeError):
    """.env에 필요한 KIS_* 값이 없을 때 발생. 어떤 값이 비었는지만 알리고
    실제 값은 절대 포함하지 않는다."""


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


@dataclass
class KisCredentials:
    app_key: str
    app_secret: str
    account_no: str
    account_product_cd: str
    env: str   # "prod" | "vps"

    @property
    def base_url(self) -> str:
        return _BASE_URLS[self.env]

    def __repr__(self) -> str:
        # 실수로 로그에 찍히더라도 실제 값이 새지 않도록 마스킹.
        # account_no도 계좌 식별정보라 앞 2자리만 남기고 가린다.
        masked_account = self.account_no[:2] + "*" * (len(self.account_no) - 2)
        return (
            f"KisCredentials(app_key='***{self.app_key[-4:]}', app_secret='***', "
            f"account_no='{masked_account}', env='{self.env}')"
        )


def load_credentials() -> KisCredentials:
    _load_dotenv_if_present()

    missing = [k for k in _ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise CredentialsMissingError(
            f"다음 환경변수가 비어 있음: {missing}. 저장소 루트의 .env.example을 "
            ".env로 복사하고 실제 값을 채운 뒤 다시 시도하세요."
        )

    env = os.environ.get("KIS_ENV", "vps")
    if env not in _BASE_URLS:
        raise CredentialsMissingError(f"KIS_ENV는 'prod' 또는 'vps'여야 함 (받은 값: {env!r})")

    return KisCredentials(
        app_key=os.environ["KIS_APP_KEY"],
        app_secret=os.environ["KIS_APP_SECRET"],
        account_no=os.environ["KIS_ACCOUNT_NO"],
        account_product_cd=os.environ["KIS_ACCOUNT_PRODUCT_CD"],
        env=env,
    )
