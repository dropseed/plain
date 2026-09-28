"""
Lifecycle discovery.

A lifecycle is what the runner does around every test without being asked:
protection, not setup. There are two places one can come from, and no others.

- Packages register a TestLifecycle subclass under the `plain.test` entry
  point group.
- The project declares its own in `tests/lifecycle.py`.

A file that is there and wrong stops the run, and so does one that holds a
lifecycle under a name the runner doesn't look for. Someone wrote it
expecting it to protect their tests. Both are a TestDefinitionError, like a
test that is written wrongly.
"""

import importlib.util
import inspect
import sys
from importlib.metadata import entry_points
from pathlib import Path

from ..definition import TestDefinitionError
from ..lifecycle import TestLifecycle

__all__ = []

_APP_LIFECYCLE_MODULE_NAME = "plain_tests_app_lifecycle"

_APP_LIFECYCLE_EXAMPLE = (
    "    from contextlib import contextmanager\n"
    "\n"
    "    from plain.test import TestLifecycle\n"
    "\n"
    "\n"
    "    class AppTestLifecycle(TestLifecycle):\n"
    "        @contextmanager\n"
    "        def around_test(self, test):\n"
    "            ...\n"
    "            yield"
)


def load_package_lifecycles() -> list[TestLifecycle]:
    """The lifecycles of the installed packages, in entry point name order."""
    from plain.runtime import settings

    lifecycles = []
    for entry_point in sorted(entry_points(group="plain.test"), key=lambda e: e.name):
        lifecycle_class = entry_point.load()
        required = lifecycle_class.required_package
        if required is not None and required not in settings.INSTALLED_PACKAGES:
            continue
        lifecycles.append(lifecycle_class())
    return lifecycles


def misplaced_app_lifecycle_paths(*, root: Path, tests_directory: Path) -> list[Path]:
    """
    The places a project lifecycle gets written by mistake. The runner reads
    none of them.
    """
    paths = [
        tests_directory / "lifecycles.py",
        tests_directory / "life_cycle.py",
        tests_directory / "lifecycle" / "__init__.py",
    ]
    if tests_directory != root:
        # Beside `tests/` instead of inside it.
        paths.append(root / "lifecycle.py")
        paths.append(root / "lifecycles.py")
    return paths


def _check_for_a_misplaced_app_lifecycle(*, root: Path, tests_directory: Path) -> None:
    for path in misplaced_app_lifecycle_paths(
        root=root, tests_directory=tests_directory
    ):
        if not path.is_file():
            continue
        # A file with one of these names that never mentions TestLifecycle is
        # something else, and none of the runner's business.
        if "TestLifecycle" not in path.read_text(errors="replace"):
            continue
        raise TestDefinitionError(
            f"{path} mentions TestLifecycle, but nothing reads it. A "
            "project's lifecycle is found by its path, and the path is\n\n"
            f"  {tests_directory / 'lifecycle.py'}\n\n"
            "Move it there. If it isn't meant to be the project's lifecycle, "
            "give the file another name."
        )


def load_app_lifecycle(*, root: Path, tests_directory: Path) -> TestLifecycle | None:
    """
    The lifecycle declared in `tests/lifecycle.py`, or None when the project
    has no such file.

    `root` is the directory `plain test` runs from, and `tests_directory` is
    the tests directory found from it. The file imports the project's helper
    modules by their bare names, as a test file does, so the caller has
    already put the directory they live in on `sys.path`.

    A file that is there but doesn't hold exactly one usable TestLifecycle
    subclass raises TestDefinitionError. It is never quietly ignored: someone
    wrote that file expecting it to protect their tests. When the file, or
    the class in it, raised an error of its own, that error is the cause.
    """
    _check_for_a_misplaced_app_lifecycle(root=root, tests_directory=tests_directory)

    path = tests_directory / "lifecycle.py"
    if not path.exists():
        return None

    spec = importlib.util.spec_from_file_location(_APP_LIFECYCLE_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise TestDefinitionError(f"{path} could not be loaded as a Python module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_APP_LIFECYCLE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(_APP_LIFECYCLE_MODULE_NAME, None)
        raise TestDefinitionError(f"{path} could not be imported.") from e

    declared = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, TestLifecycle)
        and obj.__module__ == module.__name__  # defined here, not imported
    ]

    if not declared:
        raise TestDefinitionError(
            f"{path} doesn't define a TestLifecycle subclass, so it would "
            "protect nothing. Define one:\n\n"
            f"{_APP_LIFECYCLE_EXAMPLE}"
        )
    if len(declared) > 1:
        names = ", ".join(lifecycle_class.__name__ for lifecycle_class in declared)
        raise TestDefinitionError(
            f"{path} defines {len(declared)} TestLifecycle subclasses ({names}). "
            "A project has one lifecycle. Put everything it does around a "
            "test in one class."
        )

    lifecycle_class = declared[0]
    try:
        return lifecycle_class()
    except Exception as e:
        raise TestDefinitionError(
            f"{path}: {lifecycle_class.__name__}() could not be created. The "
            "runner creates it with no arguments."
        ) from e
