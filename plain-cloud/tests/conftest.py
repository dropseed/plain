from __future__ import annotations

import keyring
import keyring.backend
import pytest


class InMemoryKeyring(keyring.backend.KeyringBackend):
    name = "in-memory"
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            from keyring.errors import PasswordDeleteError

            raise PasswordDeleteError("not found")
        del self._store[(service, username)]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point credential storage at a fresh tmp dir and clear env overrides."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PLAIN_CLOUD_TOKEN", raising=False)
    monkeypatch.delenv("PLAIN_CLOUD_API_URL", raising=False)
    return tmp_path


@pytest.fixture(autouse=True)
def fake_keyring():
    """Install an in-memory keyring backend so tests don't touch the real OS keyring."""
    backend = InMemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
