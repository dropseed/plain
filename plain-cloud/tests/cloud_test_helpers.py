"""Shared test isolation for plain-cloud: fake keyring + isolated $HOME."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Generator

import keyring
import keyring.backend

_MISSING = object()


class InMemoryKeyring(keyring.backend.KeyringBackend):
    name = "in-memory"
    priority = 1

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


@contextlib.contextmanager
def isolated_cloud_env() -> Generator[InMemoryKeyring]:
    """Point credential storage at a fresh tmp dir, clear env overrides, and
    install an in-memory keyring backend so tests don't touch the real OS
    keyring or the developer's actual home directory."""
    with tempfile.TemporaryDirectory() as tmp:
        original_home = os.environ.get("HOME", _MISSING)
        original_token = os.environ.pop("PLAIN_CLOUD_TOKEN", _MISSING)
        original_api_url = os.environ.pop("PLAIN_CLOUD_API_URL", _MISSING)
        os.environ["HOME"] = tmp

        backend = InMemoryKeyring()
        previous_keyring = keyring.get_keyring()
        keyring.set_keyring(backend)
        try:
            yield backend
        finally:
            keyring.set_keyring(previous_keyring)
            if original_home is _MISSING:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = original_home
            if original_token is not _MISSING:
                os.environ["PLAIN_CLOUD_TOKEN"] = original_token
            if original_api_url is not _MISSING:
                os.environ["PLAIN_CLOUD_API_URL"] = original_api_url
