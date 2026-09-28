import sys
import tempfile
from pathlib import Path

from plain.test import TestLifecycle, raises
from plain.testing.collection import CollectedTest
from plain.testing.lifecycles import (
    AppLifecycleError,
    app_lifecycle_path,
    load_app_lifecycle,
)
from plain.testing.runner import run_tests

RECORDING_LIFECYCLE = (
    "from contextlib import contextmanager\n"
    "\n"
    "from plain.test import TestLifecycle\n"
    "\n"
    "events = []\n"
    "\n"
    "\n"
    "class AppTestLifecycle(TestLifecycle):\n"
    "    def setup_worker(self):\n"
    "        events.append('setup')\n"
    "\n"
    "    def teardown_worker(self):\n"
    "        events.append('teardown')\n"
    "\n"
    "    @contextmanager\n"
    "    def around_test(self, test):\n"
    "        events.append(f'enter {test.id}')\n"
    "        try:\n"
    "            yield\n"
    "        finally:\n"
    "            events.append(f'exit {test.id}')\n"
)


def project_with_lifecycle(source: str) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    (root / "tests" / "lifecycle.py").write_text(source)
    return root


def test_the_one_place_is_tests_lifecycle_py():
    project = Path("/somewhere/project")
    assert app_lifecycle_path(project) == project / "tests" / "lifecycle.py"

    # A package whose test app is `tests/app` runs from inside `tests/`.
    package_tests = Path("/somewhere/package/tests")
    assert app_lifecycle_path(package_tests) == package_tests / "lifecycle.py"


def test_no_file_means_no_app_lifecycle():
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    assert load_app_lifecycle(root) is None


def test_app_lifecycle_wraps_every_test():
    root = project_with_lifecycle(RECORDING_LIFECYCLE)
    lifecycle = load_app_lifecycle(root)
    assert isinstance(lifecycle, TestLifecycle)
    events = sys.modules[type(lifecycle).__module__].events

    run = run_tests(
        [
            CollectedTest(id="t.py::test_a", func=lambda: events.append("a runs")),
            CollectedTest(id="t.py::test_b", func=lambda: events.append("b runs")),
        ],
        lifecycles=[lifecycle],
    )
    assert run.ok
    assert events == [
        "setup",
        "enter t.py::test_a",
        "a runs",
        "exit t.py::test_a",
        "enter t.py::test_b",
        "b runs",
        "exit t.py::test_b",
        "teardown",
    ]


def test_a_file_without_a_lifecycle_class_is_an_error():
    root = project_with_lifecycle(
        "from contextlib import contextmanager\n"
        "\n"
        "\n"
        "# Forgot to subclass TestLifecycle.\n"
        "class AppTestLifecycle:\n"
        "    @contextmanager\n"
        "    def around_test(self, test):\n"
        "        yield\n"
    )
    with raises(AppLifecycleError, match="doesn't define a TestLifecycle") as caught:
        load_app_lifecycle(root)
    assert "lifecycle.py" in str(caught.exception)


def test_an_imported_lifecycle_class_does_not_count_as_declared():
    root = project_with_lifecycle("from plain.test import TestLifecycle\n")
    with raises(AppLifecycleError, match="doesn't define a TestLifecycle"):
        load_app_lifecycle(root)


def test_two_lifecycle_classes_is_an_error():
    root = project_with_lifecycle(
        "from plain.test import TestLifecycle\n"
        "\n"
        "\n"
        "class NoNetwork(TestLifecycle):\n"
        "    pass\n"
        "\n"
        "\n"
        "class ResetRateLimiters(TestLifecycle):\n"
        "    pass\n"
    )
    with raises(AppLifecycleError, match="defines 2 TestLifecycle") as caught:
        load_app_lifecycle(root)
    assert "NoNetwork, ResetRateLimiters" in str(caught.exception)


def test_a_file_that_does_not_import_is_an_error():
    root = project_with_lifecycle("import does_not_exist_anywhere\n")
    with raises(AppLifecycleError, match="could not be imported") as caught:
        load_app_lifecycle(root)
    assert "does_not_exist_anywhere" in str(caught.exception)


def test_a_lifecycle_that_needs_arguments_is_an_error():
    root = project_with_lifecycle(
        "from plain.test import TestLifecycle\n"
        "\n"
        "\n"
        "class AppTestLifecycle(TestLifecycle):\n"
        "    def __init__(self, api_key):\n"
        "        self.api_key = api_key\n"
    )
    with raises(AppLifecycleError, match="could not be created"):
        load_app_lifecycle(root)
