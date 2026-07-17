from __future__ import annotations

import os

import keyring
from helpers import isolated_cloud_env
from keyring.backends.fail import Keyring as FailKeyring

from plain.cloud.credentials import (
    DEFAULT_API_URL,
    SERVICE,
    Credentials,
    KeyringUnavailable,
    clear,
    config_path,
    load,
    save,
)
from plain.test import raises


def test_save_writes_token_to_keyring_and_api_url_to_file():
    with isolated_cloud_env() as fake_keyring:
        creds = Credentials(api_url="https://example.com", token="tok-1")

        save(creds)

        assert fake_keyring.get_password(SERVICE, "https://example.com") == "tok-1"
        assert config_path().exists()
        assert 'api_url = "https://example.com"' in config_path().read_text()


def test_load_round_trip():
    with isolated_cloud_env():
        save(Credentials(api_url="https://example.com", token="tok-1"))

        loaded = load()

        assert loaded is not None
        assert loaded.api_url == "https://example.com"
        assert loaded.token == "tok-1"


def test_load_returns_none_when_nothing_saved():
    with isolated_cloud_env():
        assert load() is None


def test_env_var_overrides_stored_credentials():
    with isolated_cloud_env():
        save(Credentials(api_url="https://example.com", token="stored-token"))
        os.environ["PLAIN_CLOUD_TOKEN"] = "env-token"

        loaded = load()

        assert loaded is not None
        assert loaded.token == "env-token"
        # api_url falls back to the stored config when PLAIN_CLOUD_API_URL is unset.
        assert loaded.api_url == "https://example.com"


def test_env_var_token_with_explicit_api_url():
    with isolated_cloud_env():
        os.environ["PLAIN_CLOUD_TOKEN"] = "env-token"
        os.environ["PLAIN_CLOUD_API_URL"] = "https://staging.example.com"

        loaded = load()

        assert loaded is not None
        assert loaded.api_url == "https://staging.example.com"
        assert loaded.token == "env-token"


def test_env_var_token_alone_uses_default_api_url():
    with isolated_cloud_env():
        os.environ["PLAIN_CLOUD_TOKEN"] = "env-token"

        loaded = load()

        assert loaded is not None
        assert loaded.api_url == DEFAULT_API_URL


def test_clear_removes_token_and_config():
    with isolated_cloud_env():
        save(Credentials(api_url="https://example.com", token="tok-1"))

        assert clear() is True
        assert load() is None
        assert not config_path().exists()


def test_clear_is_idempotent():
    with isolated_cloud_env():
        assert clear() is False


def test_save_raises_when_keyring_unavailable():
    with isolated_cloud_env():
        keyring.set_keyring(FailKeyring())

        with raises(KeyringUnavailable):
            save(Credentials(api_url="https://example.com", token="tok-1"))


def test_api_url_with_quotes_is_escaped():
    """Defensive: api_url comes from a CLI flag, escape TOML special chars."""
    with isolated_cloud_env():
        save(Credentials(api_url='https://weird"host.com', token="tok-1"))

        loaded = load()
        assert loaded is not None
        assert loaded.api_url == 'https://weird"host.com'
