"""The runner collects, runs and reports tests. It knows nothing about the web.

It lives inside `plain.test`, beside the client and the captures, and takes
from the package around it only what it needs to do its job: the test it hands
to a lifecycle, the lifecycle class, the exception `skip_test` raises, and the
names of the attributes the decorators set.

This is about what the runner's code uses, not what is loaded: importing
`plain.test.runner` imports `plain.test` first, as importing any subpackage
does.
"""

import ast
from pathlib import Path

import plain.test.runner

VOCABULARY_THE_RUNNER_USES = (
    "plain.test.decorators",
    "plain.test.lifecycle",
    "plain.test.skipping",
)

WEB = (
    "plain.http",
    "plain.server",
    "plain.urls",
    "plain.views",
)


def runner_modules() -> list[Path]:
    (runner_directory,) = plain.test.runner.__path__
    modules = sorted(Path(runner_directory).glob("*.py"))
    assert len(modules) > 5
    return modules


def imported_modules(module: Path) -> list[str]:
    """Every module a runner file imports, relative imports written in full."""
    names = []
    for node in ast.walk(ast.parse(module.read_text())):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            # `from .collection import x` is level 1: plain.test.runner.
            # `from ..lifecycle import x` is level 2: plain.test.
            package = ["plain", "test", "runner"]
            base = package[: len(package) - (node.level - 1)] if node.level else []
            parts = base + ([node.module] if node.module else [])
            names.append(".".join(parts))
    return names


def is_module_or_inside(name: str, module: str) -> bool:
    return name == module or name.startswith(f"{module}.")


def test_the_runner_imports_nothing_from_the_web() -> None:
    for module in runner_modules():
        for name in imported_modules(module):
            for web_module in WEB:
                assert not is_module_or_inside(name, web_module), (
                    f"{module.name} imports {name}"
                )


def test_the_runner_takes_only_what_it_needs_from_the_vocabulary() -> None:
    taken = set()
    for module in runner_modules():
        for name in imported_modules(module):
            if not is_module_or_inside(name, "plain.test"):
                continue
            if is_module_or_inside(name, "plain.test.runner"):
                continue
            assert name in VOCABULARY_THE_RUNNER_USES, f"{module.name} imports {name}"
            taken.add(name)

    # Guards the test itself: if relative imports stopped resolving, nothing
    # would be found and the assertion above would pass on an empty set.
    assert taken == set(VOCABULARY_THE_RUNNER_USES)
