"""`plain.postgres.databases` must stay off the production runtime path.

Cluster DDL (CREATE/DROP DATABASE) needs a role with CREATEDB and a connection
to the `postgres` maintenance database. Most managed Postgres providers hand an
app a role that owns exactly one database and can't create more, so this module
is a dev/test capability only.

Keeping it in `plain.postgres` is a packaging decision (it's the package that
owns psycopg and Postgres semantics). Keeping it *unreachable* from the runtime
is what makes that safe — and this test is what enforces it, rather than
convention.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "plain" / "postgres"

FORBIDDEN_MODULE = "plain.postgres.databases"

# The modules a running production app actually loads. If a new runtime entry
# point appears, add it here.
RUNTIME_ENTRY_POINTS = [
    "plain.postgres.entrypoints",
    "plain.postgres.connection",
    "plain.postgres.query",
    "plain.postgres.middleware",
    "plain.postgres.db",
    "plain.postgres.transaction",
]


def _module_to_path(module: str) -> Path | None:
    relative = module.removeprefix("plain.postgres.").replace(".", "/")
    for candidate in (
        PACKAGE_ROOT / f"{relative}.py",
        PACKAGE_ROOT / relative / "__init__.py",
    ):
        if candidate.exists():
            return candidate
    return None


def _imported_modules(path: Path, module: str) -> set[str]:
    """Return the `plain.postgres.*` modules that `path` imports.

    Resolves relative imports against `module`'s package so `from .databases
    import ...` is caught the same as the absolute form.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    package_parts = (
        module.split(".")[:-1] if path.name != "__init__.py" else module.split(".")
    )

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            found.add(target)
            # `from plain.postgres import databases` imports a submodule too.
            for alias in node.names:
                found.add(f"{target}.{alias.name}")

    return {m for m in found if m.startswith("plain.postgres")}


def test_databases_module_is_unreachable_from_runtime() -> None:
    """Walk the import graph from every runtime entry point.

    `import plain.postgres.databases` inside a function body still counts as a
    reachable edge here. That's deliberate — a lazy import is still a runtime
    import, and the point is that production code never calls into cluster DDL
    at all.
    """
    visited: set[str] = set()
    queue = deque(RUNTIME_ENTRY_POINTS)
    # module -> the module that imported it, for a readable failure message
    imported_by: dict[str, str] = {}

    while queue:
        module = queue.popleft()
        if module in visited:
            continue
        visited.add(module)

        path = _module_to_path(module)
        if path is None:
            continue

        for imported in _imported_modules(path, module):
            if imported.startswith(FORBIDDEN_MODULE):
                chain = [imported, module]
                while chain[-1] in imported_by:
                    chain.append(imported_by[chain[-1]])
                raise AssertionError(
                    f"{FORBIDDEN_MODULE} is reachable from the runtime path: "
                    + " <- ".join(chain)
                )
            if imported not in visited:
                imported_by.setdefault(imported, module)
                queue.append(imported)


def test_test_harness_may_use_databases() -> None:
    """The test harness is the sanctioned in-package consumer."""
    path = PACKAGE_ROOT / "test" / "database.py"
    imported = _imported_modules(path, "plain.postgres.test.database")
    assert FORBIDDEN_MODULE in imported
