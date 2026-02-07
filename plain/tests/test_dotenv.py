import os

import pytest

from plain.utils.dotenv import load_dotenv, parse_dotenv


@pytest.fixture
def env_file(tmp_path):
    """Helper to create a .env file with given content."""

    def _create(content):
        path = tmp_path / ".env"
        path.write_text(content)
        return path

    return _create


@pytest.fixture(autouse=True)
def clean_env():
    """Remove test keys from os.environ after each test."""
    yield
    for key in list(os.environ):
        if key.startswith("TEST_"):
            del os.environ[key]


def test_command_substitution_sees_earlier_vars(env_file):
    """Command substitution should see variables defined earlier in the same .env file."""
    path = env_file("TEST_TOKEN=hello\nTEST_RESULT=$(echo $TEST_TOKEN)\n")
    load_dotenv(path)
    assert os.environ["TEST_TOKEN"] == "hello"
    assert os.environ["TEST_RESULT"] == "hello"


def test_command_substitution_chained(env_file):
    """Multiple command substitutions can chain through os.environ."""
    path = env_file(
        "TEST_A=first\nTEST_B=$(echo $TEST_A)-second\nTEST_C=$(echo $TEST_B)\n"
    )
    load_dotenv(path)
    assert os.environ["TEST_A"] == "first"
    assert os.environ["TEST_B"] == "first-second"
    assert os.environ["TEST_C"] == "first-second"


def test_parse_dotenv_no_environ_side_effects(env_file):
    """parse_dotenv should not modify os.environ."""
    path = env_file("TEST_PARSE_ONLY=value\n")
    result = parse_dotenv(path)
    assert result == {"TEST_PARSE_ONLY": "value"}
    assert "TEST_PARSE_ONLY" not in os.environ


def test_load_dotenv_no_override_by_default(env_file):
    """Existing env vars should not be overridden by default."""
    os.environ["TEST_EXISTING"] = "original"
    path = env_file("TEST_EXISTING=new_value\n")
    load_dotenv(path)
    assert os.environ["TEST_EXISTING"] == "original"


def test_load_dotenv_override(env_file):
    """With override=True, existing env vars should be replaced."""
    os.environ["TEST_EXISTING"] = "original"
    path = env_file("TEST_EXISTING=new_value\n")
    load_dotenv(path, override=True)
    assert os.environ["TEST_EXISTING"] == "new_value"


def test_load_dotenv_missing_file(tmp_path):
    """load_dotenv should return False for a missing file."""
    result = load_dotenv(tmp_path / "nonexistent.env")
    assert result is False


def test_load_dotenv_returns_true(env_file):
    """load_dotenv should return True when file exists."""
    path = env_file("TEST_KEY=value\n")
    result = load_dotenv(path)
    assert result is True
