"""Shared test isolation for plain-cloud: fake keyring + isolated $HOME."""

import contextlib
import os
import tempfile
from collections.abc import Generator

import keyring
import keyring.backend
from plain.testing import patch


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
    with (
        tempfile.TemporaryDirectory() as tmp,
        patch(os.environ, "HOME", tmp),
    ):
        # `patch` sets a key for the block. These two have to be gone for
        # it, which it has no way to say.
        original_token = os.environ.pop("PLAIN_CLOUD_TOKEN", None)
        original_api_url = os.environ.pop("PLAIN_CLOUD_API_URL", None)

        backend = InMemoryKeyring()
        previous_keyring = keyring.get_keyring()
        keyring.set_keyring(backend)
        try:
            yield backend
        finally:
            keyring.set_keyring(previous_keyring)
            _put_back("PLAIN_CLOUD_TOKEN", original_token)
            _put_back("PLAIN_CLOUD_API_URL", original_api_url)


def _put_back(name: str, original: str | None) -> None:
    """Leave an environment variable as it was before the block: set to
    what it held, or gone if it wasn't set, whatever the block did to it."""
    if original is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = original
