import os
from pathlib import Path

import pytest

from plain.dev import dotenv as dotenv_module
from plain.dev.dotenv import load_dotenv_files


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Each test runs in an empty cwd with the once-flag reset and a clean env."""
    monkeypatch.setattr(dotenv_module, "_files_loaded", False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLAIN_ENV", raising=False)
    baseline = set(os.environ)
    yield
    for key in set(os.environ) - baseline:
        del os.environ[key]


def _write(name: str, content: str) -> None:
    Path(name).write_text(content)


def test_unset_plain_env_loads_local_and_base():
    """With no PLAIN_ENV, only .env.local and .env load — no env-specific files."""
    _write(".env", "BASE=from-env\n")
    _write(".env.local", "LOCAL=from-env-local\n")
    _write(".env.dev", "DEV=should-not-load\n")
    load_dotenv_files()
    assert os.environ["BASE"] == "from-env"
    assert os.environ["LOCAL"] == "from-env-local"
    assert "DEV" not in os.environ


def test_dev_env_loads_full_ladder_in_precedence_order(monkeypatch):
    """`.env.{env}.local` wins over `.env.local` wins over `.env.{env}` wins over `.env`."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    _write(".env", "X=base\n")
    _write(".env.dev", "X=env-specific\n")
    _write(".env.local", "X=local\n")
    _write(".env.dev.local", "X=env-specific-local\n")
    load_dotenv_files()
    assert os.environ["X"] == "env-specific-local"


def test_test_env_skips_env_local(monkeypatch):
    """`PLAIN_ENV=test` skips .env.local (Next.js / Rails dotenv convention)."""
    monkeypatch.setenv("PLAIN_ENV", "test")
    _write(".env", "Y=base\n")
    _write(".env.local", "Y=should-be-skipped\n")
    _write(".env.test", "Y=test-value\n")
    load_dotenv_files()
    assert os.environ["Y"] == "test-value"


def test_test_env_still_loads_test_local(monkeypatch):
    """`.env.test.local` IS loaded under test (matches Next.js — only .env.local is skipped)."""
    monkeypatch.setenv("PLAIN_ENV", "test")
    _write(".env.test.local", "SECRET=from-test-local\n")
    load_dotenv_files()
    assert os.environ["SECRET"] == "from-test-local"


def test_invalid_plain_env_raises(monkeypatch):
    """A PLAIN_ENV containing path-traversal characters is rejected at the door."""
    monkeypatch.setenv("PLAIN_ENV", "staging/prod")
    with pytest.raises(ValueError, match="PLAIN_ENV must match"):
        load_dotenv_files()


def test_plain_env_with_trailing_newline_rejected(monkeypatch):
    """`re.fullmatch` (not `re.match`) closes the trailing-newline gap."""
    monkeypatch.setenv("PLAIN_ENV", "dev\n")
    with pytest.raises(ValueError, match="PLAIN_ENV must match"):
        load_dotenv_files()


def test_idempotent_within_process(monkeypatch):
    """Repeat calls are a no-op — the second invocation doesn't re-read files."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    _write(".env.dev", "FIRST=1\n")
    load_dotenv_files()
    assert os.environ["FIRST"] == "1"

    _write(".env.dev", "FIRST=2\nSECOND=2\n")
    load_dotenv_files()
    assert os.environ["FIRST"] == "1"  # not re-read
    assert "SECOND" not in os.environ


def test_silent_when_no_files_exist():
    """No .env files in cwd → no exception, no output, no env changes."""
    baseline = dict(os.environ)
    load_dotenv_files()
    assert dict(os.environ) == baseline


def test_load_notice_goes_to_stderr(monkeypatch, capsys):
    """Load notices go to stderr so JSON-producing commands keep stdout clean."""
    _write(".env", "FOO=bar\n")
    load_dotenv_files()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ".env" in captured.err
