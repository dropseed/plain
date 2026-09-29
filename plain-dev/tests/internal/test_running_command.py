"""Which command plain.dev's setup hook thinks is running.

It decides whether a database is started, so a wrong answer is a test run
with no database or a `plain docs` that starts a container.
"""

import sys

from dev_test_helpers import running
from plain.dev.utils import running_command
from plain.test import cases, patch


@cases("dev", "test", "create-user")
def test_a_process_nobody_told_is_read_from_its_arguments(command):
    with running(None), patch(sys, "argv", ["plain", command]):
        assert running_command() == command


def test_only_the_top_level_command_is_read():
    """`plain docs test` is not `plain test`."""
    with running(None), patch(sys, "argv", ["plain", "docs", "test"]):
        assert running_command() == "docs"


@cases(["plain"], ["plain", "--help"], ["plain", "--version"])
def test_a_bare_invocation_has_no_command(argv):
    with running(None), patch(sys, "argv", argv):
        assert running_command() is None


def test_what_was_said_is_believed_over_the_arguments():
    """`python -m plain.test public/test_x.py` names a target, not a command.

    Read from its arguments it was the command `public/test_x.py`, and
    `python -m plain.test` with no target was a bare `plain` that started no
    database.
    """
    arguments = ["/site-packages/plain/test/__main__.py", "public/test_x.py"]
    with running("test"), patch(sys, "argv", arguments):
        assert running_command() == "test"

    with running("test"), patch(sys, "argv", arguments[:1]):
        assert running_command() == "test"
