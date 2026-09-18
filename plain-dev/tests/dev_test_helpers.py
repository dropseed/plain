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
from plain.dev import state as state_module
from plain.test import patch

# Env vars that decide what the code under test does. Cleared on entry so a
# developer's shell (or the test runner's own database URL) can't change an
# answer.
_SCRUBBED_ENV_VARS = (
    "PLAIN_ENV",
    "DEV_ENV_KEY",
    "DATABASE_URL",
    "PLAIN_POSTGRES_URL",
)


class Sandbox:
    """An empty working directory plus its own checkout-state cache root."""

    def __init__(self, tmp_path: Path, cache_path: Path) -> None:
        self.tmp_path = tmp_path
        self.cache_path = cache_path

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
    """Run a block in an empty cwd, with a clean environment and a throwaway
    checkout-state cache root."""
    original_cwd = Path.cwd()
    original_environ = dict(os.environ)
    original_files_loaded = dotenv_module._files_loaded
    original_bound_sources = dict(dotenv_module.bound_sources)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cache_path = tmp_path / "plain-cache"

        dotenv_module._files_loaded = False
        dotenv_module.bound_sources.clear()
        for name in _SCRUBBED_ENV_VARS:
            os.environ.pop(name, None)
        if chdir:
            os.chdir(tmp_path)

        try:
            # `checkout_state_path` reads this module global on every call, so
            # patching it here redirects every caller (pointers, url cache,
            # supervisor pidfiles) at the throwaway root.
            with patch(state_module, "PLAIN_CACHE_PATH", cache_path):
                yield Sandbox(tmp_path, cache_path)
        finally:
            if chdir:
                os.chdir(original_cwd)
            os.environ.clear()
            os.environ.update(original_environ)
            dotenv_module._files_loaded = original_files_loaded
            dotenv_module.bound_sources.clear()
            dotenv_module.bound_sources.update(original_bound_sources)
