import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from plain.test import TestLifecycle, raises
from plain.test.runner.collection import RunnableTest
from plain.test.runner.execution import run_tests
from plain.test.runner.lifecycle_discovery import (
    AppLifecycleError,
    app_lifecycle_path,
    load_app_lifecycle,
)

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
            RunnableTest(id="t.py::test_a", func=lambda: events.append("a runs")),
            RunnableTest(id="t.py::test_b", func=lambda: events.append("b runs")),
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


def test_a_lifecycle_under_a_name_nothing_reads_is_refused():
    for misplaced in (
        "tests/lifecycles.py",
        "tests/life_cycle.py",
        "tests/lifecycle/__init__.py",
        "lifecycle.py",
        "lifecycles.py",
    ):
        root = Path(tempfile.mkdtemp())
        path = root / misplaced
        path.parent.mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(exist_ok=True)
        path.write_text(RECORDING_LIFECYCLE)

        with raises(AppLifecycleError) as caught:
            load_app_lifecycle(root)
        message = str(caught.exception)
        assert message.startswith(f"{path} mentions TestLifecycle")
        assert f"  {root / 'tests' / 'lifecycle.py'}\n" in message


def test_a_misplaced_lifecycle_is_refused_even_beside_the_real_one():
    root = project_with_lifecycle(RECORDING_LIFECYCLE)
    (root / "tests" / "lifecycles.py").write_text(RECORDING_LIFECYCLE)
    with raises(AppLifecycleError, match="lifecycles.py mentions TestLifecycle"):
        load_app_lifecycle(root)


def test_a_file_with_one_of_those_names_that_is_something_else_is_left_alone():
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    (root / "tests" / "lifecycles.py").write_text("ORDER_STATES = ('new', 'paid')\n")
    assert load_app_lifecycle(root) is None


def test_the_lifecycle_file_imports_helper_modules_by_their_bare_names():
    root = project_with_lifecycle(
        "from lifecycle_test_helper_module import NAME\n" + RECORDING_LIFECYCLE
    )
    (root / "tests" / "lifecycle_test_helper_module.py").write_text("NAME = 'x'\n")
    assert load_app_lifecycle(root) is not None


def test_a_lifecycle_is_handed_the_core_type():
    from plain.test import CollectedTest

    seen = []

    class Watching(TestLifecycle):
        @contextmanager
        def around_test(self, test):
            seen.append(test)
            yield

    run_tests(
        [RunnableTest(id="t.py::TestA::test_b[0]", func=lambda: None, tags=("slow",))],
        lifecycles=[Watching()],
    )
    assert isinstance(seen[0], CollectedTest)
    assert seen[0].id == "t.py::TestA::test_b[0]"
    assert seen[0].name == "TestA::test_b[0]"
    assert seen[0].tags == ("slow",)


def test_nothing_in_the_engine_is_public_api():
    import importlib
    import pkgutil

    import plain.test.runner

    modules = [plain.test.runner] + [
        importlib.import_module(f"plain.test.runner.{module.name}")
        for module in pkgutil.iter_modules(plain.test.runner.__path__)
    ]
    assert len(modules) > 5
    for module in modules:
        assert module.__all__ == []
