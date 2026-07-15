"""키움증권 REST API 인증정보 로더 (2026-07-15, KIS 분봉 한계 재검증용).

kis_credentials.py와 동일한 원칙 — APP Key/Secret은 계좌 비밀번호급
민감정보이므로 코드·저장소·대화 어디에도 하드코딩하지 않는다. 로컬
".env" 파일(.gitignore 처리됨)에서만 읽는다.

사용법: 저장소 루트의 ".env.example"을 ".env"로 복사하고 실제 값을
채운 뒤 이 모듈을 사용한다. 이 모듈은 그 값을 절대 출력(print/log)하지
않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ENV_KEYS = ("KIWOOM_APP_KEY", "KIWOOM_APP_SECRET")

_BASE_URLS = {
    "prod": "https://api.kiwoom.com",
    "mock": "https://mockapi.kiwoom.com",   # 모의투자
}


class CredentialsMissingError(RuntimeError):
    """.env에 필요한 KIWOOM_* 값이 없을 때 발생. 어떤 값이 비었는지만 알리고
    실제 값은 절대 포함하지 않는다."""


def _load_dotenv_if_present(dotenv_path: Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = dotenv_path or Path(__file__).resolve().parents[2] / ".env"
    if path.exists():
        load_dotenv(path)


@dataclass
class KiwoomCredentials:
    app_key: str
    app_secret: str
    env: str   # "prod" | "mock"

    @property
    def base_url(self) -> str:
        return _BASE_URLS[self.env]

    def __repr__(self) -> str:
        return f"KiwoomCredentials(app_key='***{self.app_key[-4:]}', app_secret='***', env='{self.env}')"


def load_credentials() -> KiwoomCredentials:
    _load_dotenv_if_present()

    missing = [k for k in _ENV_KEYS if not os.environ.get(k)]
    if missing:
        raise CredentialsMissingError(
            f"다음 환경변수가 비어 있음: {missing}. 저장소 루트의 .env.example을 "
            ".env로 복사하고 실제 값을 채운 뒤 다시 시도하세요."
        )

    env = os.environ.get("KIWOOM_ENV", "mock")
    if env not in _BASE_URLS:
        raise CredentialsMissingError(f"KIWOOM_ENV는 'prod' 또는 'mock'이어야 함 (받은 값: {env!r})")

    return KiwoomCredentials(
        app_key=os.environ["KIWOOM_APP_KEY"],
        app_secret=os.environ["KIWOOM_APP_SECRET"],
        env=env,
    )
