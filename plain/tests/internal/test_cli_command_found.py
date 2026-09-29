"""The CLI says when the command it was given turns out to be one.

`plain.runtime.setup()` runs before the CLI knows whether a name is a
command: a package or the app may register it, and they aren't loaded until
then. So a hook that runs during setup runs for a mistyped command too. What
it would start and leave running waits to hear the command was found.
"""

from collections.abc import Generator
from contextlib import contextmanager

import click
import plain.runtime
from click.testing import CliRunner
from plain.cli import core
from plain.cli.runtime import (
    get_running_command,
    running_command_is_found,
    set_running_command,
    the_running_command_was_found,
    when_the_running_command_is_found,
)
from plain.testing import patch


@contextmanager
def what_this_process_is_running_put_back() -> Generator[None]:
    """The CLI is run in this process, which is itself running a command."""
    said_before = get_running_command()
    was_found_before = running_command_is_found()
    try:
        yield
    finally:
        set_running_command(said_before)
        if was_found_before:
            the_running_command_was_found()


def test_a_command_that_does_not_exist_is_never_said_to_be_found():
    started = []

    def setup_with_a_hook_that_starts_something() -> None:
        when_the_running_command_is_found(lambda: started.append("services"))

    with (
        what_this_process_is_running_put_back(),
        patch(core, "entry_points", lambda group: []),
        patch(plain.runtime, "setup", setup_with_a_hook_that_starts_something),
    ):
        result = CliRunner().invoke(
            core.PlainCommandCollection(), ["tset"], prog_name="plain"
        )

        assert result.exit_code == 2
        assert "No such command 'tset'" in result.output
        assert get_running_command() == "tset"
        assert running_command_is_found() is False
        assert started == []


def test_a_command_that_exists_is_found_before_it_runs():
    started = []

    @click.command()
    def hello() -> None:
        click.echo(f"found: {running_command_is_found()}")
        when_the_running_command_is_found(lambda: started.append("services"))

    class FakeEntryPoint:
        name = "hello"
        value = "fake_package.cli:hello"
        dist = None

        def load(self) -> click.Command:
            return hello

    with (
        what_this_process_is_running_put_back(),
        patch(core, "entry_points", lambda group: [FakeEntryPoint()]),
        patch(plain.runtime, "setup", lambda: None),
    ):
        result = CliRunner().invoke(
            core.PlainCommandCollection(), ["hello"], prog_name="plain"
        )

        assert result.exit_code == 0
        assert "found: True" in result.output
        assert started == ["services"]


def test_what_waited_for_one_command_is_not_done_for_the_next():
    started = []

    with what_this_process_is_running_put_back():
        set_running_command("tset")
        when_the_running_command_is_found(lambda: started.append("for tset"))

        set_running_command("shell")
        the_running_command_was_found()

        assert started == []


def test_a_process_nobody_named_a_command_for_does_it_now():
    started = []

    with what_this_process_is_running_put_back():
        set_running_command(None)
        when_the_running_command_is_found(lambda: started.append("services"))

        assert started == ["services"]
