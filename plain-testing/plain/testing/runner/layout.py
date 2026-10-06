"""
Where a project keeps its tests.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = []

# Test modules are named for where they are, under this name, so two files
# called `test_views.py` in different directories are different modules.
TEST_MODULES_PACKAGE = "plain_tests"


@dataclass(frozen=True, kw_only=True)
class Layout:
    """Where one run's tests and helper modules are."""

    root: Path
    helper_directory: Path
    # The top-level name a test module may not import through (`tests`).
    refused_import_name: str | None

    def shown(self, path: Path) -> str:
        """A path the way the run's output writes it: relative to the root."""
        return path_as_shown(path, root=self.root)


def path_as_shown(path: Path, *, root: Path) -> str:
    """
    A path the way a run's output writes it: relative to `root` when it is
    under it, and as it was given when it isn't.
    """
    if path.is_absolute() and path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return str(path)


def find_tests_directory(root: Path) -> Path:
    """
    The tests directory for a run started in `root`: the one place helper
    modules are imported from, and where `lifecycle.py` lives.

    `root` is normally the project root, with `tests/` beside `app/`. A
    package whose test app is `tests/app` runs from inside `tests/`, so there
    the root is the tests directory.
    """
    if root.name == "tests":
        return root
    return root / "tests"


def import_helper_modules_from(directory: Path) -> None:
    """
    Put the directory helper modules live in on `sys.path`, so a test file
    and `lifecycle.py` both import `<directory>/helpers.py` as `helpers`.
    """
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))


def without_test_module_names(text: str) -> str:
    """
    Text with the names test modules are loaded under taken out of it, so
    that what a test file defines is called what the file calls it.

    A test file is a module named for where it is
    (`plain_tests.tests.billing.test_refunds`), and Python puts a module's
    name in front of what it defines: `<plain_tests.tests.billing.
    test_refunds.FakeGateway object at 0x...>`. Nobody wrote that name, and
    a report already says which file it is about. This is `<FakeGateway
    object at 0x...>`.
    """
    if TEST_MODULES_PACKAGE not in text:
        return text
    names = [
        name
        for name, module in sys.modules.items()
        if name.startswith(f"{TEST_MODULES_PACKAGE}.")
        and getattr(module, "__file__", None)
    ]
    # The longest first: `plain_tests.tests.test_a` is the start of
    # `plain_tests.tests.test_a_b`.
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(f"{name}.", "")
    return text
