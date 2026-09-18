import contextlib
import io
import os

from helpers import sandbox
from plain.dev.dotenv import load_dotenv_files
from plain.test import raises


def test_unset_plain_env_loads_local_and_base():
    """With no PLAIN_ENV, only .env.local and .env load — no env-specific files."""
    with sandbox() as box:
        box.write(".env", "BASE=from-env\n")
        box.write(".env.local", "LOCAL=from-env-local\n")
        box.write(".env.dev", "DEV=should-not-load\n")
        load_dotenv_files()
        assert os.environ["BASE"] == "from-env"
        assert os.environ["LOCAL"] == "from-env-local"
        assert "DEV" not in os.environ


def test_dev_env_loads_full_ladder_in_precedence_order():
    """`.env.{env}.local` wins over `.env.local` wins over `.env.{env}` wins over `.env`."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env", "X=base\n")
        box.write(".env.dev", "X=env-specific\n")
        box.write(".env.local", "X=local\n")
        box.write(".env.dev.local", "X=env-specific-local\n")
        load_dotenv_files()
        assert os.environ["X"] == "env-specific-local"


def test_test_env_skips_env_local():
    """`PLAIN_ENV=test` skips .env.local (Next.js / Rails dotenv convention)."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "test"
        box.write(".env", "Y=base\n")
        box.write(".env.local", "Y=should-be-skipped\n")
        box.write(".env.test", "Y=test-value\n")
        load_dotenv_files()
        assert os.environ["Y"] == "test-value"


def test_test_env_still_loads_test_local():
    """`.env.test.local` IS loaded under test (matches Next.js — only .env.local is skipped)."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "test"
        box.write(".env.test.local", "SECRET=from-test-local\n")
        load_dotenv_files()
        assert os.environ["SECRET"] == "from-test-local"


def test_invalid_plain_env_raises():
    """A PLAIN_ENV containing path-traversal characters is rejected at the door."""
    with sandbox():
        os.environ["PLAIN_ENV"] = "staging/prod"
        with raises(ValueError, match="PLAIN_ENV must match"):
            load_dotenv_files()


def test_plain_env_with_trailing_newline_rejected():
    """`re.fullmatch` (not `re.match`) closes the trailing-newline gap."""
    with sandbox():
        os.environ["PLAIN_ENV"] = "dev\n"
        with raises(ValueError, match="PLAIN_ENV must match"):
            load_dotenv_files()


def test_idempotent_within_process():
    """Repeat calls are a no-op — the second invocation doesn't re-read files."""
    with sandbox() as box:
        os.environ["PLAIN_ENV"] = "dev"
        box.write(".env.dev", "FIRST=1\n")
        load_dotenv_files()
        assert os.environ["FIRST"] == "1"

        box.write(".env.dev", "FIRST=2\nSECOND=2\n")
        load_dotenv_files()
        assert os.environ["FIRST"] == "1"  # not re-read
        assert "SECOND" not in os.environ


def test_silent_when_no_files_exist():
    """No .env files in cwd → no exception, no output, no env changes."""
    with sandbox():
        baseline = dict(os.environ)
        load_dotenv_files()
        assert dict(os.environ) == baseline


def test_load_notice_goes_to_stderr():
    """Load notices go to stderr so JSON-producing commands keep stdout clean."""
    with sandbox() as box:
        box.write(".env", "FOO=bar\n")
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            load_dotenv_files()
        assert out.getvalue() == ""
        assert ".env" in err.getvalue()
