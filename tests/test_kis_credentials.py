import pytest

from phase0.config.kis_credentials import CredentialsMissingError, KisCredentials, load_credentials


def test_load_credentials_raises_clear_error_when_missing(monkeypatch):
    for key in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "KIS_ACCOUNT_PRODUCT_CD", "KIS_ENV"):
        monkeypatch.delenv(key, raising=False)
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
    assert creds.base_url == "https://openapi.koreainvestment.com:9443"


def test_invalid_env_value_rejected(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_ACCOUNT_PRODUCT_CD", "01")
    monkeypatch.setenv("KIS_ENV", "not-a-real-env")
    with pytest.raises(CredentialsMissingError):
        load_credentials()
