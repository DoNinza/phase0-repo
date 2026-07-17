"""OpenAI API 인증정보 로더 — GPT-5.6 Sol 코드 리뷰 하네스용.

kis_credentials.py/dart_credentials.py와 동일 원칙: 인증키는 코드·저장소·
대화 어디에도 하드코딩하지 않고 로컬 ".env"(.gitignore 처리됨)에서만
읽는다. 이 모듈은 그 값을 절대 출력(print/log)하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class CredentialsMissingError(RuntimeError):
    """.env에 OPENAI_API_KEY가 없을 때 발생. 실제 값은 절대 포함하지 않는다."""


def _load_dotenv_if_present(dotenv_path: Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = dotenv_path or Path(__file__).resolve().parents[2] / ".env"
    if path.exists():
        load_dotenv(path)


@dataclass
class OpenAiCredentials:
    api_key: str

    def __repr__(self) -> str:
        return f"OpenAiCredentials(api_key='***{self.api_key[-4:]}')"


def load_credentials() -> OpenAiCredentials:
    _load_dotenv_if_present()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise CredentialsMissingError(
            "OPENAI_API_KEY가 비어 있음. 저장소 루트의 .env에 "
            "platform.openai.com에서 발급받은 API 키를 채운 뒤 다시 시도하세요."
        )

    return OpenAiCredentials(api_key=api_key)
