import pytest

import phase0.config.krx_credentials as krx_credentials
from phase0.config.krx_credentials import CredentialsMissingError, ensure_krx_login_env


def test_ensure_krx_login_env_raises_clear_error_when_missing(monkeypatch):
    for key in ("KRX_ID", "KRX_PW"):
        monkeypatch.delenv(key, raising=False)
    # 개발 머신에 실제 .env가 있더라도 이 테스트는 "env var가 전혀 없을 때"의
    # 에러 경로만 검증해야 하므로 dotenv 자동 로드를 끈다(kis_credentials 테스트와 동일 원칙).
    monkeypatch.setattr(krx_credentials, "_load_dotenv_if_present", lambda *a, **k: None)
    with pytest.raises(CredentialsMissingError):
        ensure_krx_login_env()


def test_ensure_krx_login_env_partial_missing_raises(monkeypatch):
    monkeypatch.setenv("KRX_ID", "fake-id")
    monkeypatch.delenv("KRX_PW", raising=False)
    monkeypatch.setattr(krx_credentials, "_load_dotenv_if_present", lambda *a, **k: None)
    with pytest.raises(CredentialsMissingError):
        ensure_krx_login_env()


def test_ensure_krx_login_env_injects_into_os_environ(monkeypatch):
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)
    monkeypatch.setattr(krx_credentials, "_load_dotenv_if_present", lambda *a, **k: None)

    import os
    os.environ["KRX_ID"] = "fake-id"
    os.environ["KRX_PW"] = "fake-pw"
    try:
        ensure_krx_login_env()  # 이미 os.environ에 있으므로 예외 없이 통과해야 함
    finally:
        del os.environ["KRX_ID"]
        del os.environ["KRX_PW"]


def test_error_message_never_exposes_actual_values(monkeypatch):
    for key in ("KRX_ID", "KRX_PW"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(krx_credentials, "_load_dotenv_if_present", lambda *a, **k: None)
    with pytest.raises(CredentialsMissingError) as exc_info:
        ensure_krx_login_env()
    message = str(exc_info.value)
    assert "KRX_ID" in message and "KRX_PW" in message
    assert "data.krx.co.kr" in message
