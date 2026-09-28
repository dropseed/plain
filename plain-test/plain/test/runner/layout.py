"""
Where a project keeps its tests.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = []


@dataclass(frozen=True, kw_only=True)
class Layout:
    """Where one run's tests and helper modules are."""

    root: Path
    helper_directory: Path
    # The top-level name a test module may not import through (`tests`).
    refused_import_name: str | None

    def shown(self, path: Path) -> str:
        """A path the way the run's output writes it: relative to the root."""
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
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
