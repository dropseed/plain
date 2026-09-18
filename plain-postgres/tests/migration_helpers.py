"""Shared helpers for tests that write migration files on disk."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from plain.postgres.migrations.loader import MigrationLoader

TEMP_MIGRATIONS_MODULE = "temp_migrations_under_test"


@contextmanager
def temp_migrations(*labels: str) -> Generator[Path]:
    """Point packages at migrations written under a temporary directory.

        with temp_migrations("examples", "plaintemplates") as root:
            (root / "examples" / "0001_initial.py").write_text(...)

    Each label becomes an importable subpackage the loader reads instead of
    the package's real migrations. Modules imported this way are purged from
    `sys.modules` afterwards so the next test starts from its own files.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        root = tmp_dir / TEMP_MIGRATIONS_MODULE
        root.mkdir()
        (root / "__init__.py").write_text("")
        for label in labels:
            (root / label).mkdir()
            (root / label / "__init__.py").write_text("")

        original = MigrationLoader.migrations_module

        def migrations_module(package_label: str) -> tuple[str | None, bool]:
            if package_label in labels:
                return f"{TEMP_MIGRATIONS_MODULE}.{package_label}", False
            return original(package_label)

        sys.path.insert(0, str(tmp_dir))
        MigrationLoader.migrations_module = staticmethod(migrations_module)  # type: ignore[method-assign]
        try:
            yield root
        finally:
            MigrationLoader.migrations_module = original  # type: ignore[method-assign]
            try:
                sys.path.remove(str(tmp_dir))
            except ValueError:
                pass
            for name in list(sys.modules):
                if name == TEMP_MIGRATIONS_MODULE or name.startswith(
                    f"{TEMP_MIGRATIONS_MODULE}."
                ):
                    del sys.modules[name]
