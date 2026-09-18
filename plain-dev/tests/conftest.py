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
    monkeypatch.setattr("plain.dev.state.PLAIN_CACHE_PATH", cache)
    return cache
