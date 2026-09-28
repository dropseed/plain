"""The test package is built on core's public API.

It used to subclass the private handler and call its underscore methods to
run a request, and set underscore attributes on the `Request` it built.
Core now offers both as supported API (`Request(body=...)`,
`plain.server.inprocess`), and nothing in `plain.test` reaches past them.
"""

import ast
from pathlib import Path

import plain.test


def plain_test_modules() -> list[Path]:
    (package_directory,) = plain.test.__path__
    # Recursive, so the runner's modules are held to the same rule.
    modules = sorted(Path(package_directory).rglob("*.py"))
    assert modules
    return modules


def imported_names(tree: ast.AST) -> list[str]:
    """Every `module` and `module.name` a file imports, wherever in the file."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_plain_test_imports_nothing_private_from_core() -> None:
    for module in plain_test_modules():
        for name in imported_names(ast.parse(module.read_text())):
            if not name.startswith("plain."):
                continue
            assert not name.startswith("plain.internal"), f"{module.name}: {name}"
            private_parts = [part for part in name.split(".") if part.startswith("_")]
            assert not private_parts, f"{module.name}: {name}"


def test_plain_test_sets_no_underscore_attribute_on_a_request() -> None:
    for module in plain_test_modules():
        for node in ast.walk(ast.parse(module.read_text())):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id not in ("request", "http_request"):
                continue
            assert not node.attr.startswith("_"), (
                f"{module.name}:{node.lineno}: request.{node.attr}"
            )
