from __future__ import annotations

import os

from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult

# The `PLAIN_`-prefixed variables core sets itself. They are not settings, so
# they are not typos.
NON_SETTING_ENV_VARS = frozenset(
    {
        "PLAIN_SETTINGS_MODULE",  # which settings module to import
        "PLAIN_ENV",  # which `.env` files load, set by the CLI for `plain dev` / `plain test`
    }
)


@register_check(name="settings.unused_env_vars")
class CheckUnusedEnvVars(PreflightCheck):
    """Detect environment variables that look like settings but aren't used."""

    def run(self) -> list[PreflightResult]:
        results: list[PreflightResult] = []

        # Get all env vars matching any configured prefix
        for prefix in settings._env_prefixes:
            for key in os.environ:
                if key in NON_SETTING_ENV_VARS:
                    continue
                if key.startswith(prefix) and key.isupper():
                    setting_name = key[len(prefix) :]
                    # Skip empty setting names (just the prefix itself)
                    if setting_name and setting_name not in settings._settings:
                        results.append(
                            PreflightResult(
                                fix=f"Environment variable '{key}' looks like a setting but "
                                f"'{setting_name}' is not a recognized setting.",
                                id="settings.unused_env_var",
                                warning=True,
                            )
                        )

        # Warn if PLAIN_ env vars exist but PLAIN_ not in prefixes
        if "PLAIN_" not in settings._env_prefixes:
            plain_vars = [
                k
                for k in os.environ
                if k.startswith("PLAIN_")
                and k.isupper()
                and k not in NON_SETTING_ENV_VARS
            ]
            if plain_vars:
                results.append(
                    PreflightResult(
                        fix=f"Found PLAIN_ environment variables but 'PLAIN_' is not in "
                        f"ENV_SETTINGS_PREFIXES: {', '.join(sorted(plain_vars))}",
                        id="settings.plain_prefix_disabled",
                        warning=True,
                    )
                )

        return results
