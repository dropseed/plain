"""Dev services are started for a command that exists, and not before.

plain.dev's setup hook runs for every `plain` command, one that was mistyped
included, because the CLI can't tell it from a command the app registers
until the app has loaded. Services the hook started for `plain test`, with no
plain.test installed to provide the command, were left running after the CLI
said there was no such command.
"""

import sys

from dev_test_helpers import running, sandbox
from plain.cli.runtime import (
    the_running_command_was_found,
    when_the_running_command_is_found,
)
from plain.dev import entrypoints, services
from plain.dev.services import ServicesSupervisor, auto_start_services
from plain.test import cases, patch


class StartedServices:
    """What stands in for the supervisor: it has services to start, none is
    running, and starting them is written down and nothing else."""

    def __init__(self) -> None:
        self.times_started = 0
        self.running = False

    def get_services(self, root):
        return {"search": {"cmd": "run-the-search-server"}}

    def running_pid(self):
        return 4321 if self.running else None

    def spawn_background(self):
        self.times_started += 1
        self.running = True


def with_services_to_start(started: StartedServices):
    return (
        patch(ServicesSupervisor, "get_services", staticmethod(started.get_services)),
        patch(ServicesSupervisor, "running_pid", staticmethod(started.running_pid)),
        patch(
            ServicesSupervisor,
            "spawn_background",
            staticmethod(started.spawn_background),
        ),
        patch(services.os.environ, "DEV_SERVICES_AUTO", "true"),
        patch(services.click, "secho", lambda *args, **kwargs: None),
        # It waits for the supervisor to come up. This one is up at once.
        patch(services.time, "sleep", lambda seconds: None),
    )


def the_setup_hook_is_run() -> None:
    """In an empty directory, and with no database looked for."""
    with sandbox(), patch(entrypoints, "_ensure_managed_postgres", lambda: None):
        entrypoints.setup()


def test_the_setup_hook_waits_for_the_command_to_be_found():
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running("test"):
        the_setup_hook_is_run()
        assert started.times_started == 0

        the_running_command_was_found()
        assert started.times_started == 1


@cases("test", "tset")
def test_the_setup_hook_starts_nothing_for_a_command_that_is_never_found(command):
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f:
        with running(command):
            the_setup_hook_is_run()
        assert started.times_started == 0


def test_services_are_not_started_until_the_command_is_found():
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running("test"):
        when_the_running_command_is_found(auto_start_services)
        assert started.times_started == 0

        the_running_command_was_found()
        assert started.times_started == 1


@cases("test", "tset", "request")
def test_a_command_that_is_never_found_starts_nothing(command):
    """`plain test` with no plain.test installed is one."""
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f:
        with running(command):
            when_the_running_command_is_found(auto_start_services)
        # The process goes on to say there is no such command, and ends.
        assert started.times_started == 0


def test_a_command_found_before_the_hook_runs_has_them_started_at_once():
    """`python -m plain.test` is the command, and says so before it sets up."""
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running("test"):
        the_running_command_was_found()
        when_the_running_command_is_found(auto_start_services)
        assert started.times_started == 1


def test_a_command_that_needs_no_services_has_none_started_when_found():
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running("docs"):
        when_the_running_command_is_found(auto_start_services)
        the_running_command_was_found()
        assert started.times_started == 0


def test_a_process_nobody_named_a_command_for_is_read_from_its_arguments():
    """A script that calls `setup()`. There is nothing to wait for."""
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running(None), patch(sys, "argv", ["plain", "shell"]):
        when_the_running_command_is_found(auto_start_services)
        assert started.times_started == 1


@cases(["plain"], ["plain", "--help"])
def test_a_bare_plain_starts_nothing(argv):
    started = StartedServices()
    a, b, c, d, e, f = with_services_to_start(started)
    with a, b, c, d, e, f, running(None), patch(sys, "argv", argv):
        when_the_running_command_is_found(auto_start_services)
        assert started.times_started == 0
