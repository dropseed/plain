import contextlib
import io
import os
import tempfile
from pathlib import Path

from plain.dev import dotenv as dotenv_module
from plain.dev.dotenv import load_dotenv_files
from plain.test import raises

_MISSING = object()


@contextlib.contextmanager
def _isolated():
    """Each test runs in an empty cwd with the once-flag reset and a clean env."""
    original_loaded = dotenv_module._files_loaded
    dotenv_module._files_loaded = False
    original_cwd = os.getcwd()
    original_plain_env = os.environ.pop("PLAIN_ENV", _MISSING)
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        baseline = set(os.environ)
        try:
            yield
        finally:
            for key in set(os.environ) - baseline:
                del os.environ[key]
            os.chdir(original_cwd)
            dotenv_module._files_loaded = original_loaded
            if original_plain_env is not _MISSING:
                os.environ["PLAIN_ENV"] = original_plain_env


def _write(name: str, content: str) -> None:
    Path(name).write_text(content)


def test_unset_plain_env_loads_local_and_base():
    """With no PLAIN_ENV, only .env.local and .env load — no env-specific files."""
    with _isolated():
        _write(".env", "BASE=from-env\n")
        _write(".env.local", "LOCAL=from-env-local\n")
        _write(".env.dev", "DEV=should-not-load\n")
        load_dotenv_files()
        assert os.environ["BASE"] == "from-env"
        assert os.environ["LOCAL"] == "from-env-local"
        assert "DEV" not in os.environ


def test_dev_env_loads_full_ladder_in_precedence_order():
    """`.env.{env}.local` wins over `.env.local` wins over `.env.{env}` wins over `.env`."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "dev"
        _write(".env", "X=base\n")
        _write(".env.dev", "X=env-specific\n")
        _write(".env.local", "X=local\n")
        _write(".env.dev.local", "X=env-specific-local\n")
        load_dotenv_files()
        assert os.environ["X"] == "env-specific-local"


def test_test_env_skips_env_local():
    """`PLAIN_ENV=test` skips .env.local (Next.js / Rails dotenv convention)."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "test"
        _write(".env", "Y=base\n")
        _write(".env.local", "Y=should-be-skipped\n")
        _write(".env.test", "Y=test-value\n")
        load_dotenv_files()
        assert os.environ["Y"] == "test-value"


def test_test_env_still_loads_test_local():
    """`.env.test.local` IS loaded under test (matches Next.js — only .env.local is skipped)."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "test"
        _write(".env.test.local", "SECRET=from-test-local\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-test-local"


def test_invalid_plain_env_raises():
    """A PLAIN_ENV containing path-traversal characters is rejected at the door."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "staging/prod"
        with raises(ValueError, match="PLAIN_ENV must match"):
            load_dotenv_files()


def test_plain_env_with_trailing_newline_rejected():
    """`re.fullmatch` (not `re.match`) closes the trailing-newline gap."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "dev\n"
        with raises(ValueError, match="PLAIN_ENV must match"):
            load_dotenv_files()


def test_idempotent_within_process():
    """Repeat calls are a no-op — the second invocation doesn't re-read files."""
    with _isolated():
        os.environ["PLAIN_ENV"] = "dev"
        _write(".env.dev", "FIRST=1\n")
        load_dotenv_files()
        assert os.environ["FIRST"] == "1"

        _write(".env.dev", "FIRST=2\nSECOND=2\n")
        load_dotenv_files()
        assert os.environ["FIRST"] == "1"  # not re-read
        assert "SECOND" not in os.environ


def test_silent_when_no_files_exist():
    """No .env files in cwd → no exception, no output, no env changes."""
    with _isolated():
        baseline = dict(os.environ)
        load_dotenv_files()
        assert dict(os.environ) == baseline


def test_load_notice_goes_to_stderr():
    """Load notices go to stderr so JSON-producing commands keep stdout clean."""
    with _isolated():
        _write(".env", "FOO=bar\n")
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            load_dotenv_files()
        assert out.getvalue() == ""
        assert ".env" in err.getvalue()
