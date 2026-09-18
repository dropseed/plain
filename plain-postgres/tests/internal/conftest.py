from __future__ import annotations

import sys
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from plain.postgres.migrations.loader import MigrationLoader

TEMP_MIGRATIONS_MODULE = "temp_migrations_under_test"


@pytest.fixture
def temp_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Callable[..., Path]]:
    """Point packages at migrations written under tmp_path during the test.

        root = temp_migrations("examples", "plaintemplates")
        (root / "examples" / "0001_initial.py").write_text(...)

    Each label becomes an importable subpackage the loader reads instead of
    the package's real migrations. Modules imported this way are purged from
    `sys.modules` afterwards so the next test starts from its own files.
    """
    root = tmp_path / TEMP_MIGRATIONS_MODULE
    root.mkdir()
    (root / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    original = MigrationLoader.migrations_module
    redirected: set[str] = set()

    def migrations_module(package_label: str) -> tuple[str | None, bool]:
        if package_label in redirected:
            return f"{TEMP_MIGRATIONS_MODULE}.{package_label}", False
        return original(package_label)

    monkeypatch.setattr(
        MigrationLoader, "migrations_module", staticmethod(migrations_module)
    )

    def redirect(*labels: str) -> Path:
        for label in labels:
            (root / label).mkdir()
            (root / label / "__init__.py").write_text("")
            redirected.add(label)
        return root

    yield redirect

    for name in list(sys.modules):
        if name == TEMP_MIGRATIONS_MODULE or name.startswith(
            f"{TEMP_MIGRATIONS_MODULE}."
        ):
            del sys.modules[name]
