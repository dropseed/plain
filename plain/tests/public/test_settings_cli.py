from click.testing import CliRunner
from plain.cli.core import cli
from plain.runtime import settings
from plain.testing import override_settings

# Distinctive enough that finding it anywhere in the output means it leaked.
SECRET_VALUE = "tok_4f9c2e71b8d3"


def _settings_get(*args: str):
    return CliRunner().invoke(cli, ["settings", "get", *args], prog_name="plain")


def test_get_prints_an_ordinary_setting():
    result = _settings_get("DEBUG")
    assert result.exit_code == 0
    assert result.stdout == f"{settings.DEBUG}\n"


def test_get_masks_a_secret_by_default():
    with override_settings(SECRET_KEY=SECRET_VALUE):
        result = _settings_get("SECRET_KEY")
    assert result.exit_code == 0
    assert result.stdout == "********\n"
    assert SECRET_VALUE not in result.output
    assert "--reveal" in result.stderr


def test_get_reveal_prints_a_secret():
    with override_settings(SECRET_KEY=SECRET_VALUE):
        result = _settings_get("SECRET_KEY", "--reveal")
    assert result.exit_code == 0
    assert result.stdout == f"{SECRET_VALUE}\n"


def test_get_unknown_setting_fails_on_stderr():
    result = _settings_get("NOT_A_SETTING")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "NOT_A_SETTING" in result.stderr
