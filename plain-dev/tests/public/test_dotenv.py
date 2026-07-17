import contextlib
import os
import tempfile
from pathlib import Path

from plain.dev.dotenv import load_dotenv, parse_dotenv


@contextlib.contextmanager
def env_file(content):
    """Create a .env file with given content, cleaning up TEST_ env vars after."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".env"
        path.write_text(content)
        try:
            yield path
        finally:
            for key in list(os.environ):
                if key.startswith("TEST_"):
                    del os.environ[key]


def test_command_substitution_sees_earlier_vars():
    """Command substitution should see variables defined earlier in the same .env file."""
    with env_file("TEST_TOKEN=hello\nTEST_RESULT=$(echo $TEST_TOKEN)\n") as path:
        load_dotenv(path)
        assert os.environ["TEST_TOKEN"] == "hello"
        assert os.environ["TEST_RESULT"] == "hello"


def test_command_substitution_chained():
    """Multiple command substitutions can chain through os.environ."""
    with env_file(
        "TEST_A=first\nTEST_B=$(echo $TEST_A)-second\nTEST_C=$(echo $TEST_B)\n"
    ) as path:
        load_dotenv(path)
        assert os.environ["TEST_A"] == "first"
        assert os.environ["TEST_B"] == "first-second"
        assert os.environ["TEST_C"] == "first-second"


def test_parse_dotenv_no_environ_side_effects():
    """parse_dotenv should not modify os.environ."""
    with env_file("TEST_PARSE_ONLY=value\n") as path:
        result = parse_dotenv(path)
        assert result == {"TEST_PARSE_ONLY": "value"}
        assert "TEST_PARSE_ONLY" not in os.environ


def test_load_dotenv_no_override_by_default():
    """Existing env vars should not be overridden by default."""
    os.environ["TEST_EXISTING"] = "original"
    with env_file("TEST_EXISTING=new_value\n") as path:
        load_dotenv(path)
        assert os.environ["TEST_EXISTING"] == "original"


def test_load_dotenv_override():
    """With override=True, existing env vars should be replaced."""
    os.environ["TEST_EXISTING"] = "original"
    with env_file("TEST_EXISTING=new_value\n") as path:
        load_dotenv(path, override=True)
        assert os.environ["TEST_EXISTING"] == "new_value"


def test_load_dotenv_missing_file():
    """load_dotenv should return False for a missing file."""
    with tempfile.TemporaryDirectory() as tmp:
        result = load_dotenv(Path(tmp) / "nonexistent.env")
        assert result is False


def test_load_dotenv_returns_true():
    """load_dotenv should return True when file exists."""
    with env_file("TEST_KEY=value\n") as path:
        result = load_dotenv(path)
        assert result is True
