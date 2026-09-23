import pytest
from click.testing import CliRunner
from plain.cli.core import cli
from plain.runtime import settings

# Distinctive enough that finding it anywhere in the output means it leaked.
SECRET_VALUE = "tok_4f9c2e71b8d3"


@pytest.fixture
def secret_key():
    original = settings.SECRET_KEY
    settings.SECRET_KEY = SECRET_VALUE
    yield SECRET_VALUE
    settings.SECRET_KEY = original


def _settings_get(*args: str):
    return CliRunner().invoke(cli, ["settings", "get", *args], prog_name="plain")


def test_get_prints_an_ordinary_setting():
    result = _settings_get("DEBUG")
    assert result.exit_code == 0
    assert result.stdout == f"{settings.DEBUG}\n"


def test_get_masks_a_secret_by_default(secret_key):
    result = _settings_get("SECRET_KEY")
    assert result.exit_code == 0
    assert result.stdout == "********\n"
    assert secret_key not in result.output
    assert "--reveal" in result.stderr


def test_get_reveal_prints_a_secret(secret_key):
    result = _settings_get("SECRET_KEY", "--reveal")
    assert result.exit_code == 0
    assert result.stdout == f"{secret_key}\n"


def test_get_unknown_setting_fails_on_stderr():
    result = _settings_get("NOT_A_SETTING")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "NOT_A_SETTING" in result.stderr
