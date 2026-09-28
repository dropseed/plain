"""
Lifecycle discovery.

A lifecycle is what the runner does around every test without being asked:
protection, not setup. There are two places one can come from, and no others.

- Packages register a TestLifecycle subclass under the `plain.testing` entry
  point group.
- The project declares its own in `tests/lifecycle.py`.
"""

import importlib.util
import inspect
import sys
from importlib.metadata import entry_points
from pathlib import Path

from plain.test.lifecycle import TestLifecycle

__all__ = [
    "AppLifecycleError",
    "load_app_lifecycle",
    "load_package_lifecycles",
]

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


class AppLifecycleError(Exception):
    """`tests/lifecycle.py` exists but doesn't declare a usable lifecycle."""


def load_package_lifecycles() -> list[TestLifecycle]:
    """The lifecycles of the installed packages, in entry point name order."""
    from plain.runtime import settings

    lifecycles = []
    for entry_point in sorted(
        entry_points(group="plain.testing"), key=lambda e: e.name
    ):
        lifecycle_class = entry_point.load()
        required = lifecycle_class.required_package
        if required is not None and required not in settings.INSTALLED_PACKAGES:
            continue
        lifecycles.append(lifecycle_class())
    return lifecycles


def app_lifecycle_path(root: Path) -> Path:
    """
    Where the project's own lifecycle lives: `tests/lifecycle.py`.

    `root` is the directory `plain test` runs from. That is normally the
    project root, with `tests/` inside it. A package whose test app lives in
    `tests/app` runs from inside `tests/`, so there the root is that
    directory.
    """
    tests_directory = root if root.name == "tests" else root / "tests"
    return tests_directory / "lifecycle.py"


def load_app_lifecycle(root: Path) -> TestLifecycle | None:
    """
    The lifecycle declared in `tests/lifecycle.py`, or None when the project
    has no such file.

    A file that is there but doesn't hold exactly one usable TestLifecycle
    subclass raises AppLifecycleError. It is never quietly ignored: someone
    wrote that file expecting it to protect their tests.
    """
    path = app_lifecycle_path(root)
    if not path.exists():
        return None

    # The file can import the project's test helpers, which are found from
    # the root — the same root collection puts on sys.path.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    spec = importlib.util.spec_from_file_location(_APP_LIFECYCLE_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise AppLifecycleError(f"{path} could not be loaded as a Python module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_APP_LIFECYCLE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(_APP_LIFECYCLE_MODULE_NAME, None)
        raise AppLifecycleError(
            f"{path} could not be imported.\n\n  {type(e).__name__}: {e}"
        ) from e

    declared = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, TestLifecycle)
        and obj.__module__ == module.__name__  # defined here, not imported
    ]

    if not declared:
        raise AppLifecycleError(
            f"{path} doesn't define a TestLifecycle subclass, so it would "
            "protect nothing. Define one:\n\n"
            f"{_APP_LIFECYCLE_EXAMPLE}"
        )
    if len(declared) > 1:
        names = ", ".join(lifecycle_class.__name__ for lifecycle_class in declared)
        raise AppLifecycleError(
            f"{path} defines {len(declared)} TestLifecycle subclasses ({names}). "
            "A project has one lifecycle. Put everything it does around a "
            "test in one class."
        )

    lifecycle_class = declared[0]
    try:
        return lifecycle_class()
    except Exception as e:
        raise AppLifecycleError(
            f"{path}: {lifecycle_class.__name__}() could not be created. The "
            "runner creates it with no arguments.\n\n"
            f"  {type(e).__name__}: {e}"
        ) from e
