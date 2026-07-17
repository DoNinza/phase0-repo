"""금융감독원 OpenDART 인증정보 로더 (뉴스·펀더멘털 전략 트랙 — PEAD).

kis_credentials.py와 동일한 원칙: 인증키는 코드·저장소·대화 어디에도
하드코딩하지 않고 로컬 ".env"(.gitignore 처리됨)에서만 읽는다. 이 모듈은
그 값을 절대 출력(print/log)하지 않는다.

참고: docs/news_fundamentals_전략_기획안.md §2.2
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class CredentialsMissingError(RuntimeError):
    """.env에 DART_API_KEY가 없을 때 발생. 실제 값은 절대 포함하지 않는다."""


def _load_dotenv_if_present(dotenv_path: Path | None = None) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = dotenv_path or Path(__file__).resolve().parents[2] / ".env"
    if path.exists():
        load_dotenv(path)


@dataclass
class DartCredentials:
    api_key: str

    def __repr__(self) -> str:
        return f"DartCredentials(api_key='***{self.api_key[-4:]}')"


def load_credentials() -> DartCredentials:
    _load_dotenv_if_present()

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise CredentialsMissingError(
            "DART_API_KEY가 비어 있음. 저장소 루트의 .env에 "
            "https://opendart.fss.or.kr 에서 발급받은 인증키를 채운 뒤 다시 시도하세요."
        )

    return DartCredentials(api_key=api_key)
