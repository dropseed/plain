import os

import pytest
from plain.dev.dotenv import load_dotenv_files


def test_unset_plain_env_loads_local_and_base(write):
    """With no PLAIN_ENV, only .env.local and .env load — no env-specific files."""
    write(".env", "BASE=from-env\n")
    write(".env.local", "LOCAL=from-env-local\n")
    write(".env.dev", "DEV=should-not-load\n")
    load_dotenv_files()
    assert os.environ["BASE"] == "from-env"
    assert os.environ["LOCAL"] == "from-env-local"
    assert "DEV" not in os.environ


def test_dev_env_loads_full_ladder_in_precedence_order(write, monkeypatch):
    """`.env.{env}.local` wins over `.env.local` wins over `.env.{env}` wins over `.env`."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env", "X=base\n")
    write(".env.dev", "X=env-specific\n")
    write(".env.local", "X=local\n")
    write(".env.dev.local", "X=env-specific-local\n")
    load_dotenv_files()
    assert os.environ["X"] == "env-specific-local"


def test_test_env_skips_env_local(write, monkeypatch):
    """`PLAIN_ENV=test` skips .env.local (Next.js / Rails dotenv convention)."""
    monkeypatch.setenv("PLAIN_ENV", "test")
    write(".env", "Y=base\n")
    write(".env.local", "Y=should-be-skipped\n")
    write(".env.test", "Y=test-value\n")
    load_dotenv_files()
    assert os.environ["Y"] == "test-value"


def test_test_env_still_loads_test_local(write, monkeypatch):
    """`.env.test.local` IS loaded under test (matches Next.js — only .env.local is skipped)."""
    monkeypatch.setenv("PLAIN_ENV", "test")
    write(".env.test.local", "SECRET=from-test-local\n")
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


def test_idempotent_within_process(write, monkeypatch):
    """Repeat calls are a no-op — the second invocation doesn't re-read files."""
    monkeypatch.setenv("PLAIN_ENV", "dev")
    write(".env.dev", "FIRST=1\n")
    load_dotenv_files()
    assert os.environ["FIRST"] == "1"

    write(".env.dev", "FIRST=2\nSECOND=2\n")
    load_dotenv_files()
    assert os.environ["FIRST"] == "1"  # not re-read
    assert "SECOND" not in os.environ


def test_silent_when_no_files_exist():
    """No .env files in cwd → no exception, no output, no env changes."""
    baseline = dict(os.environ)
    load_dotenv_files()
    assert dict(os.environ) == baseline


def test_load_notice_goes_to_stderr(write, monkeypatch, capsys):
    """Load notices go to stderr so JSON-producing commands keep stdout clean."""
    write(".env", "FOO=bar\n")
    load_dotenv_files()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ".env" in captured.err
