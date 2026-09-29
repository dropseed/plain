import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from plain.testing import TestDefinitionError, TestLifecycle, raises
from plain.testing.runner.collection import RunnableTest
from plain.testing.runner.execution import run_tests
from plain.testing.runner.layout import (
    find_tests_directory,
    import_helper_modules_from,
)
from plain.testing.runner.lifecycle_discovery import load_app_lifecycle

RECORDING_LIFECYCLE = (
    "from contextlib import contextmanager\n"
    "\n"
    "from plain.testing import TestLifecycle\n"
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


def load_lifecycle_of_a_run_started_in(root: Path) -> TestLifecycle | None:
    """What the command does with the directory it is run from."""
    tests_directory = find_tests_directory(root)
    import_helper_modules_from(tests_directory)
    return load_app_lifecycle(root=root, tests_directory=tests_directory)


def test_the_tests_directory_is_tests_or_the_directory_itself():
    project = Path("/somewhere/project")
    assert find_tests_directory(project) == project / "tests"

    # A package whose test app is `tests/app` runs from inside `tests/`.
    package_tests = Path("/somewhere/package/tests")
    assert find_tests_directory(package_tests) == package_tests


def test_the_lifecycle_of_a_run_started_inside_tests_is_beside_the_test_files():
    root = Path(tempfile.mkdtemp()) / "tests"
    root.mkdir()
    (root / "lifecycle.py").write_text(RECORDING_LIFECYCLE)
    assert load_lifecycle_of_a_run_started_in(root) is not None


def test_no_file_means_no_app_lifecycle():
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    assert load_lifecycle_of_a_run_started_in(root) is None


def test_app_lifecycle_wraps_every_test():
    root = project_with_lifecycle(RECORDING_LIFECYCLE)
    lifecycle = load_lifecycle_of_a_run_started_in(root)
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
    with raises(TestDefinitionError, match="doesn't define a TestLifecycle") as caught:
        load_lifecycle_of_a_run_started_in(root)
    assert "lifecycle.py" in str(caught.exception)


def test_an_imported_lifecycle_class_does_not_count_as_declared():
    root = project_with_lifecycle("from plain.testing import TestLifecycle\n")
    with raises(TestDefinitionError, match="doesn't define a TestLifecycle"):
        load_lifecycle_of_a_run_started_in(root)


def test_two_lifecycle_classes_is_an_error():
    root = project_with_lifecycle(
        "from plain.testing import TestLifecycle\n"
        "\n"
        "\n"
        "class NoNetwork(TestLifecycle):\n"
        "    pass\n"
        "\n"
        "\n"
        "class ResetRateLimiters(TestLifecycle):\n"
        "    pass\n"
    )
    with raises(TestDefinitionError, match="defines 2 TestLifecycle") as caught:
        load_lifecycle_of_a_run_started_in(root)
    assert "NoNetwork, ResetRateLimiters" in str(caught.exception)


def test_a_file_that_does_not_import_is_an_error():
    root = project_with_lifecycle("import does_not_exist_anywhere\n")
    with raises(TestDefinitionError, match="could not be imported") as caught:
        load_lifecycle_of_a_run_started_in(root)
    # What went wrong inside the file is the cause, which the command prints
    # with its traceback.
    assert isinstance(caught.exception.__cause__, ModuleNotFoundError)
    assert "does_not_exist_anywhere" in str(caught.exception.__cause__)


def test_a_lifecycle_that_needs_arguments_is_an_error():
    root = project_with_lifecycle(
        "from plain.testing import TestLifecycle\n"
        "\n"
        "\n"
        "class AppTestLifecycle(TestLifecycle):\n"
        "    def __init__(self, api_key):\n"
        "        self.api_key = api_key\n"
    )
    with raises(TestDefinitionError, match="could not be created") as caught:
        load_lifecycle_of_a_run_started_in(root)
    assert isinstance(caught.exception.__cause__, TypeError)


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

        with raises(TestDefinitionError) as caught:
            load_lifecycle_of_a_run_started_in(root)
        message = str(caught.exception)
        assert message.startswith(f"{path} mentions TestLifecycle")
        assert f"  {root / 'tests' / 'lifecycle.py'}\n" in message


def test_a_misplaced_lifecycle_is_refused_even_beside_the_real_one():
    root = project_with_lifecycle(RECORDING_LIFECYCLE)
    (root / "tests" / "lifecycles.py").write_text(RECORDING_LIFECYCLE)
    with raises(TestDefinitionError, match="lifecycles.py mentions TestLifecycle"):
        load_lifecycle_of_a_run_started_in(root)


def test_a_file_with_one_of_those_names_that_is_something_else_is_left_alone():
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    (root / "tests" / "lifecycles.py").write_text("ORDER_STATES = ('new', 'paid')\n")
    assert load_lifecycle_of_a_run_started_in(root) is None


def test_the_lifecycle_file_imports_helper_modules_by_their_bare_names():
    root = project_with_lifecycle(
        "from lifecycle_test_helper_module import NAME\n" + RECORDING_LIFECYCLE
    )
    (root / "tests" / "lifecycle_test_helper_module.py").write_text("NAME = 'x'\n")
    assert load_lifecycle_of_a_run_started_in(root) is not None


def test_a_lifecycle_is_handed_the_core_type():
    from plain.testing import CollectedTest

    seen = []

    class Watching(TestLifecycle):
        @contextmanager
        def around_test(self, test):
            seen.append(test)
            yield

    run_tests(
        [RunnableTest(id="t.py::test_b[0]", func=lambda: None, tags=("slow",))],
        lifecycles=[Watching()],
    )
    assert isinstance(seen[0], CollectedTest)
    assert seen[0].id == "t.py::test_b[0]"
    assert seen[0].name == "test_b[0]"
    assert seen[0].tags == ("slow",)


def test_nothing_in_the_engine_is_public_api():
    import importlib
    import pkgutil

    import plain.testing.runner

    modules = [plain.testing.runner] + [
        importlib.import_module(f"plain.testing.runner.{module.name}")
        for module in pkgutil.iter_modules(plain.testing.runner.__path__)
    ]
    assert len(modules) > 5
    for module in modules:
        assert module.__all__ == []
