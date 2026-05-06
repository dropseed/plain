from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from plain.cli.options import SettingOption


@click.command()
@click.option(
    "--value",
    type=int,
    cls=SettingOption,
    setting="ENV_SETTING",
)
def sample_cmd(value):
    click.echo(f"value={value}")


def test_cli_arg_overrides_setting():
    runner = CliRunner()
    # ENV_SETTING is set to 1 via conftest.py env var
    result = runner.invoke(sample_cmd, ["--value", "42"])
    assert result.exit_code == 0
    assert "value=42" in result.output


def test_setting_from_env_var():
    runner = CliRunner()
    # ENV_SETTING = 1 (set via PLAIN_ENV_SETTING in conftest.py)
    result = runner.invoke(sample_cmd, [])
    assert result.exit_code == 0
    assert "value=1" in result.output


def test_none_when_setting_not_found():
    @click.command()
    @click.option(
        "--value",
        type=int,
        cls=SettingOption,
        setting="NONEXISTENT_SETTING_XYZ",
    )
    def cmd(value):
        click.echo(f"value={value}")

    runner = CliRunner()
    result = runner.invoke(cmd, [])
    assert result.exit_code == 0
    assert "value=None" in result.output


def test_setting_from_explicit_value():
    @click.command()
    @click.option(
        "--value",
        type=str,
        cls=SettingOption,
        setting="EXPLICIT_SETTING",
    )
    def cmd(value):
        click.echo(f"value={value}")

    runner = CliRunner()
    result = runner.invoke(cmd, [])
    assert result.exit_code == 0
    assert "value=explicitly changed" in result.output


def test_raises_if_both_setting_and_envvar():
    with pytest.raises(ValueError, match="Cannot use both"):

        @click.command()
        @click.option(
            "--value",
            type=int,
            cls=SettingOption,
            setting="SOME_SETTING",
            envvar="SOME_ENV_VAR",
        )
        def cmd(value):
            pass


def test_raises_if_both_setting_and_default():
    with pytest.raises(ValueError, match="Cannot use both"):

        @click.command()
        @click.option(
            "--value",
            type=int,
            cls=SettingOption,
            setting="SOME_SETTING",
            default=42,
        )
        def cmd(value):
            pass


def test_none_valued_setting():
    """A setting that exists but has None as its value passes through as None."""

    @click.command()
    @click.option(
        "--value",
        type=int,
        cls=SettingOption,
        setting="NULLABLE_SETTING",
    )
    def cmd(value):
        click.echo(f"value={value}")

    runner = CliRunner()
    result = runner.invoke(cmd, [])
    assert result.exit_code == 0
    assert "value=None" in result.output


def test_package_default_is_used():
    """Package defaults flow through SettingOption as the single source of truth."""

    @click.command()
    @click.option(
        "--value",
        type=str,
        cls=SettingOption,
        setting="DEFAULT_SETTING",
    )
    def cmd(value):
        click.echo(f"value={value}")

    runner = CliRunner()
    result = runner.invoke(cmd, [])
    assert result.exit_code == 0
    assert "value=unchanged default" in result.output
