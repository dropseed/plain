from __future__ import annotations

import contextlib
import os

from plain.preflight.settings import CheckUnusedEnvVars
from plain.test import patch


@contextlib.contextmanager
def _fixes(**env: str):
    """Yield the joined fixes reported while `env` is set."""
    with contextlib.ExitStack() as stack:
        for name, value in env.items():
            stack.enter_context(patch(os.environ, name, value))
        yield " ".join(result.fix for result in CheckUnusedEnvVars().run())


def test_unknown_plain_env_var_is_reported() -> None:
    with _fixes(PLAIN_NOT_A_SETTING="x") as fixes:
        assert "PLAIN_NOT_A_SETTING" in fixes


def test_plain_env_vars_that_are_not_settings_are_exempt() -> None:
    """These configure Plain itself — they aren't misspelled settings."""
    with _fixes(PLAIN_SETTINGS_MODULE="app.settings", PLAIN_ENV="dev") as fixes:
        assert "'SETTINGS_MODULE' is not a recognized setting" not in fixes
        assert "'ENV' is not a recognized setting" not in fixes
