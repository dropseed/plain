import os

from dev_test_helpers import sandbox
from plain.dev.dotenv import load_dotenv, parse_dotenv


def test_command_substitution_is_literal_text():
    """Nothing in a .env file runs: $(...) is just characters."""
    with sandbox() as box:
        box.write(".env", "TEST_TOKEN=hello\nTEST_RESULT=$(echo $TEST_TOKEN)\n")
        assert parse_dotenv(".env")["TEST_RESULT"] == "$(echo hello)"


def test_parse_dotenv_no_environ_side_effects():
    """parse_dotenv should not modify os.environ."""
    with sandbox() as box:
        box.write(".env", "TEST_PARSE_ONLY=value\n")
        assert parse_dotenv(".env") == {"TEST_PARSE_ONLY": "value"}
        assert "TEST_PARSE_ONLY" not in os.environ


def test_load_dotenv_no_override_by_default():
    """Existing env vars should not be overridden by default."""
    with sandbox() as box:
        os.environ["TEST_EXISTING"] = "original"
        box.write(".env", "TEST_EXISTING=new_value\n")
        load_dotenv(".env")
        assert os.environ["TEST_EXISTING"] == "original"


def test_load_dotenv_override():
    """With override=True, existing env vars should be replaced."""
    with sandbox() as box:
        os.environ["TEST_EXISTING"] = "original"
        box.write(".env", "TEST_EXISTING=new_value\n")
        load_dotenv(".env", override=True)
        assert os.environ["TEST_EXISTING"] == "new_value"


def test_load_dotenv_missing_file():
    """load_dotenv should return False for a missing file."""
    with sandbox():
        assert load_dotenv("nonexistent.env") is False


def test_load_dotenv_returns_true():
    """load_dotenv should return True when file exists."""
    with sandbox() as box:
        box.write(".env", "TEST_KEY=value\n")
        assert load_dotenv(".env") is True
