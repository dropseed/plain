from __future__ import annotations

import pytest
from plain.preflight.settings import CheckUnusedEnvVars


def _fixes(monkeypatch: pytest.MonkeyPatch, **env: str) -> str:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return " ".join(result.fix for result in CheckUnusedEnvVars().run())


def test_unknown_plain_env_var_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "PLAIN_NOT_A_SETTING" in _fixes(monkeypatch, PLAIN_NOT_A_SETTING="x")


def test_plain_env_vars_that_are_not_settings_are_exempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """These configure Plain itself — they aren't misspelled settings."""
    fixes = _fixes(
        monkeypatch,
        PLAIN_SETTINGS_MODULE="app.settings",
        PLAIN_ENV="dev",
    )
    assert "'SETTINGS_MODULE' is not a recognized setting" not in fixes
    assert "'ENV' is not a recognized setting" not in fixes
