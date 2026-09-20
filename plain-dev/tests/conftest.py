from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_checkout_state(tmp_path, monkeypatch):
    """Point checkout state at a throwaway cache root.

    It lives outside the checkout (see `plain.dev.state`), so without this a
    test that writes a pointer for a `tmp_path` "checkout" would leave a real
    entry in the developer's own cache — once per run, never collected.
    """
    cache = tmp_path / "plain-cache"
    monkeypatch.setattr("plain.runtime.PLAIN_CACHE_PATH", cache)
    return cache


@pytest.fixture(autouse=True)
def isolated_env_keys(tmp_path, monkeypatch):
    """Point the env key store at a throwaway directory.

    It lives in the developer's home (see `plain.dev.envkeys`), so without this
    a test that runs `plain env init` would leave a real key there.
    """
    store = tmp_path / "env-keys"
    monkeypatch.setattr("plain.dev.envkeys.ENV_KEYS_PATH", store)
    return store
