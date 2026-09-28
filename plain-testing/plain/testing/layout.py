"""
Where a project keeps its tests.
"""

from pathlib import Path

__all__ = []


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
