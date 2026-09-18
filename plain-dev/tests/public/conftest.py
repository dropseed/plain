from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from plain.dev import dotenv as dotenv_module


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test runs in an empty cwd with the once-flag reset and a clean env."""
    monkeypatch.setattr(dotenv_module, "_files_loaded", False)
    dotenv_module.bound_sources.clear()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLAIN_ENV", raising=False)
    monkeypatch.delenv("DEV_ENV_KEY", raising=False)
    baseline = set(os.environ)
    yield
    for key in set(os.environ) - baseline:
        del os.environ[key]


@pytest.fixture
def write() -> Callable[[str, str], None]:
    """Write a file in the test's isolated cwd."""

    def _write(name: str, content: str) -> None:
        Path(name).write_text(content)

    return _write


@pytest.fixture
def reload_dotenv_files(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Load the `.env` ladder again — `load_dotenv_files` only loads once per process."""

    def _reload() -> None:
        monkeypatch.setattr(dotenv_module, "_files_loaded", False)
        dotenv_module.load_dotenv_files()

    return _reload
