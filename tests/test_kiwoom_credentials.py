import pytest

import phase0.config.kiwoom_credentials as kiwoom_credentials
from phase0.config.kiwoom_credentials import CredentialsMissingError, load_credentials


def test_load_credentials_raises_clear_error_when_missing(monkeypatch):
    for key in ("KIWOOM_APP_KEY", "KIWOOM_APP_SECRET", "KIWOOM_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(kiwoom_credentials, "_load_dotenv_if_present", lambda *a, **k: None)
    with pytest.raises(CredentialsMissingError):
        load_credentials()


def test_load_credentials_reads_env_vars(monkeypatch):
    monkeypatch.setenv("KIWOOM_APP_KEY", "fake-key-1234")
    monkeypatch.setenv("KIWOOM_APP_SECRET", "fake-secret")
    monkeypatch.setenv("KIWOOM_ENV", "mock")

    creds = load_credentials()
    assert creds.app_key == "fake-key-1234"
    assert creds.base_url == "https://mockapi.kiwoom.com"


def test_credentials_repr_never_exposes_secret(monkeypatch):
    monkeypatch.setenv("KIWOOM_APP_KEY", "fake-key-1234")
    monkeypatch.setenv("KIWOOM_APP_SECRET", "super-secret-value")
    monkeypatch.setenv("KIWOOM_ENV", "prod")

    creds = load_credentials()
    assert "super-secret-value" not in repr(creds)
    assert creds.base_url == "https://api.kiwoom.com"


def test_invalid_env_value_rejected(monkeypatch):
    monkeypatch.setenv("KIWOOM_APP_KEY", "k")
    monkeypatch.setenv("KIWOOM_APP_SECRET", "s")
    monkeypatch.setenv("KIWOOM_ENV", "not-a-real-env")
    with pytest.raises(CredentialsMissingError):
        load_credentials()
