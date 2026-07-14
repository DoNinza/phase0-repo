import pytest

import phase0.config.kis_credentials as kis_credentials
from phase0.config.kis_credentials import CredentialsMissingError, KisCredentials, load_credentials


def test_load_credentials_raises_clear_error_when_missing(monkeypatch):
    for key in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "KIS_ACCOUNT_PRODUCT_CD", "KIS_ENV"):
        monkeypatch.delenv(key, raising=False)
    # 개발 머신의 실제 .env가 존재하더라도(있어야 정상) 이 테스트는 "env var가
    # 전혀 없을 때"의 에러 경로만 검증해야 하므로 dotenv 자동 로드를 끈다.
    monkeypatch.setattr(kis_credentials, "_load_dotenv_if_present", lambda *a, **k: None)
    with pytest.raises(CredentialsMissingError):
        load_credentials()


def test_load_credentials_reads_env_vars(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "fake-key-1234")
    monkeypatch.setenv("KIS_APP_SECRET", "fake-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CD", "01")
    monkeypatch.setenv("KIS_ENV", "vps")

    creds = load_credentials()
    assert creds.app_key == "fake-key-1234"
    assert creds.account_no == "12345678"
    assert creds.base_url == "https://openapivts.koreainvestment.com:29443"


def test_credentials_repr_never_exposes_secret(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "fake-key-1234")
    monkeypatch.setenv("KIS_APP_SECRET", "super-secret-value")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CD", "01")
    monkeypatch.setenv("KIS_ENV", "prod")

    creds = load_credentials()
    assert "super-secret-value" not in repr(creds)
    assert "12345678" not in repr(creds)  # account_no도 마스킹 대상
    assert creds.base_url == "https://openapi.koreainvestment.com:9443"


def test_invalid_env_value_rejected(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CD", "01")
    monkeypatch.setenv("KIS_ENV", "not-a-real-env")
    with pytest.raises(CredentialsMissingError):
        load_credentials()
