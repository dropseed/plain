from click.testing import CliRunner

from plain.cli.core import cli


def test_plain_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"], prog_name="plain")
    assert result.exit_code == 0
    assert result.output.startswith("Usage: plain")


def test_plain_cli_build():
    runner = CliRunner()
    result = runner.invoke(cli, ["build"], prog_name="plain")
    assert result.exit_code == 0
    assert "Compiled 0 assets into 0 files" in result.output


def test_plain_help_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["help"], prog_name="plain")
    assert result.exit_code == 0
    assert "Usage: plain build" in result.output
    assert "Usage: plain shell" in result.output
