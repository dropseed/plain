"""Auth and sessions are separate packages, and their test helpers ship with
them: `plain.auth.test`, `plain.sessions.test`. `plain.testing` imports neither,
and its client carries no method that would need to."""

import ast
from pathlib import Path

import plain.testing
from plain.testing import Client, cases


def imported_module_names(source: str) -> list[str]:
    """Every module a file imports, wherever in the file the import is."""
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def test_plain_test_imports_no_optional_package() -> None:
    (package_directory,) = plain.testing.__path__
    modules = sorted(Path(package_directory).rglob("*.py"))
    assert modules

    for module in modules:
        for name in imported_module_names(module.read_text()):
            assert not name.startswith("plain.auth"), module.name
            assert not name.startswith("plain.sessions"), module.name


@cases("force_login", "logout", "session", "trace", "handler")
def test_client_does_not_have(name: str) -> None:
    assert not hasattr(Client, name)
    assert name not in vars(Client())
