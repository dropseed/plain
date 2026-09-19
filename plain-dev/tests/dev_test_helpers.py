"""Shared sandbox for the plain.dev tests.

Every test here reads or writes something that lives *outside* the checkout —
`os.environ`, the working directory, the checkout state under
`PLAIN_CACHE_PATH`. `sandbox()` scopes all of that to a `with` block so a test
can't leave a real entry in the developer's own cache or leak an env var into
the next test.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from plain.dev import dotenv as dotenv_module
from plain.dev import envkeys as envkeys_module
from plain.dev import state as state_module
from plain.test import patch

# Env vars that decide what the code under test does. Cleared on entry so a
# developer's shell (or the test runner's own database URL) can't change an
# answer.
_SCRUBBED_ENV_VARS = (
    "PLAIN_ENV",
    "PLAIN_ENV_KEY",
    "PLAIN_ENV_KEY_ID",
    "DEV_ENV_KEY",
    "DATABASE_URL",
    "PLAIN_POSTGRES_URL",
)


class Sandbox:
    """An empty working directory, its own checkout-state cache root, and its
    own env-key store."""

    def __init__(self, tmp_path: Path, cache_path: Path, env_keys_path: Path) -> None:
        self.tmp_path = tmp_path
        self.cache_path = cache_path
        self.env_keys_path = env_keys_path

    def write(self, name: str, content: str) -> Path:
        """Write a file in the sandbox's working directory."""
        path = self.tmp_path / name
        path.write_text(content)
        return path

    def reload_dotenv_files(self) -> None:
        """Load the `.env` ladder again — `load_dotenv_files` only loads once
        per process."""
        dotenv_module._files_loaded = False
        dotenv_module.load_dotenv_files()


@contextmanager
def sandbox(*, chdir: bool = True) -> Generator[Sandbox]:
    """Run a block in an empty cwd, with a clean environment, a throwaway
    checkout-state cache root and a throwaway env-key store."""
    original_cwd = Path.cwd()
    original_environ = dict(os.environ)
    original_files_loaded = dotenv_module._files_loaded
    original_consumed_env_key = dotenv_module._consumed_env_key
    original_directives = dict(dotenv_module._directives)
    original_bound_sources = dict(dotenv_module.bound_sources)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cache_path = tmp_path / "plain-cache"
        env_keys_path = tmp_path / "env-keys"

        dotenv_module._files_loaded = False
        dotenv_module._consumed_env_key = None
        dotenv_module._directives = {}
        dotenv_module.bound_sources.clear()
        for name in _SCRUBBED_ENV_VARS:
            os.environ.pop(name, None)
        if chdir:
            os.chdir(tmp_path)

        try:
            # `checkout_state_path` reads this module global on every call, so
            # patching it here redirects every caller (pointers, url cache,
            # supervisor pidfiles) at the throwaway root. `stored_env_key_path`
            # reads its own global the same way, so the key store follows.
            with (
                patch(state_module, "PLAIN_CACHE_PATH", cache_path),
                patch(envkeys_module, "ENV_KEYS_PATH", env_keys_path),
            ):
                yield Sandbox(tmp_path, cache_path, env_keys_path)
        finally:
            if chdir:
                os.chdir(original_cwd)
            os.environ.clear()
            os.environ.update(original_environ)
            dotenv_module._files_loaded = original_files_loaded
            dotenv_module._consumed_env_key = original_consumed_env_key
            dotenv_module._directives = original_directives
            dotenv_module.bound_sources.clear()
            dotenv_module.bound_sources.update(original_bound_sources)
