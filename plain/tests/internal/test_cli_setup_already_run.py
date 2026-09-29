"""The CLI invoked in a process where `setup()` has already been called.

A test run sets the app up and then tests invoke commands in-process, so
the CLI lets "already set up" through. It used to let it through whether
or not that earlier setup had finished, and went on to load commands for an
app that wasn't there.
"""

from plain.cli import core
from plain.packages import packages_registry
from plain.testing import patch

from plain import runtime


def already_set_up():
    raise runtime.SetupError("Plain runtime is already set up.")


def test_a_runtime_that_is_set_up_loads_the_registry():
    assert packages_registry.ready

    collection = core.PlainCommandCollection()
    with patch(runtime, "setup", already_set_up):
        collection._load_registry()

    assert collection._setup_error is None
    assert collection._registry_group is not None


def test_a_setup_that_did_not_finish_is_an_error_not_a_loaded_app():
    collection = core.PlainCommandCollection()
    with (
        patch(runtime, "setup", already_set_up),
        patch(packages_registry, "ready", False),
    ):
        collection._load_registry()

    assert isinstance(collection._setup_error, runtime.SetupError)
    assert "didn't finish" in str(collection._setup_error)
    assert collection._registry_group is None


def test_a_setup_that_found_no_app_is_reported_as_no_app():
    collection = core.PlainCommandCollection()
    with (
        patch(runtime, "setup", already_set_up),
        patch(packages_registry, "ready", False),
        patch(runtime, "APP_PATH", runtime.APP_PATH / "no-such-directory"),
    ):
        collection._load_registry()

    assert isinstance(collection._setup_error, runtime.AppPathNotFound)
