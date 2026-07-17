"""
Test collection.

Conventions: files named `test_*.py` (searched recursively from the target),
functions named `test_*`, and classes named `Test*` containing `test_*`
methods (a fresh instance per test). Test modules get assertion rewriting
when imported; helper modules do not.
"""

from __future__ import annotations

import ast
import functools
import inspect
import os
import sys
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from plain.test.decorators import (
    TEST_CASES_ATTRIBUTE,
    TEST_SKIP_ATTRIBUTE,
    TEST_TAGS_ATTRIBUTE,
)

from .assertions import rewrite_asserts

__all__ = ["CollectedTest", "collect_tests", "CollectionError"]

_SKIP_DIR_NAMES = {"__pycache__", "node_modules"}


class CollectionError(Exception):
    def __init__(self, path: Path, error: BaseException) -> None:
        self.path = path
        self.error = error
        super().__init__(f"Failed to collect {path}: {error!r}")


@dataclass
class CollectedTest:
    id: str  # e.g. "public/test_client.py::test_get" or "...::TestX::test_y[0]"
    func: Callable  # zero-argument callable that runs the test body
    tags: tuple[str, ...] = ()
    skip_reason: str | None = None

    @property
    def name(self) -> str:
        """The test's name within its file (e.g. "TestX::test_y[0]")."""
        return self.id.partition("::")[2]


def collect_tests(
    targets: list[str],
    *,
    root: Path | None = None,
    exclude_dirs: Iterable[str] = (),
) -> list[CollectedTest]:
    """
    Collect tests from the given targets (files, directories, or
    `path::test_name` ids), relative to `root` (default: cwd).

    `exclude_dirs` adds directory names to skip during discovery (e.g. the
    runner excludes the Plain `app` directory in app mode).
    """
    root = (root or Path.cwd()).resolve()
    skip_dir_names = _SKIP_DIR_NAMES | set(exclude_dirs)

    # Test modules import helpers (and each other's routers/models) as
    # top-level modules, so the root goes on sys.path.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    collected: list[CollectedTest] = []
    for target in targets or ["."]:
        path_part, _, name_part = target.partition("::")
        base = (root / path_part).resolve() if path_part not in ("", ".") else root

        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = _find_test_files(base, skip_dir_names=skip_dir_names)
        else:
            raise FileNotFoundError(f"No such test target: {target}")

        for file in files:
            tests = _collect_file(file, root=root)
            if name_part:
                tests = [
                    t
                    for t in tests
                    if t.name == name_part or t.name.startswith(f"{name_part}[")
                ]
            collected.extend(tests)

    # De-duplicate (overlapping targets) while preserving order.
    seen: set[str] = set()
    unique = []
    for test in collected:
        if test.id not in seen:
            seen.add(test.id)
            unique.append(test)
    return unique


def _find_test_files(directory: Path, *, skip_dir_names: set[str]) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(directory):
        # Prune skipped directories in place so os.walk never descends into
        # them (rglob can't prune — a .venv or node_modules would get a full
        # tree walk).
        dirnames[:] = sorted(
            d for d in dirnames if d not in skip_dir_names and not d.startswith(".")
        )
        files.extend(
            Path(dirpath) / f
            for f in sorted(filenames)
            if f.startswith("test_") and f.endswith(".py")
        )
    return files


def _collect_file(path: Path, *, root: Path) -> list[CollectedTest]:
    module = _import_test_module(path, root=root)
    relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else path

    tests: list[CollectedTest] = []
    for name, obj in vars(module).items():
        if getattr(obj, "__module__", None) != module.__name__:
            continue  # imported, not defined here

        if inspect.isfunction(obj) and name.startswith("test_"):
            tests.extend(_expand(obj, base_id=f"{relative}::{name}"))
        elif inspect.isclass(obj) and name.startswith("Test"):
            tests.extend(_collect_class(obj, relative=str(relative)))

    return tests


def _collect_class(cls: type, *, relative: str) -> list[CollectedTest]:
    methods = [
        (name, obj)
        for name, obj in vars(cls).items()
        if inspect.isfunction(obj) and name.startswith("test_")
    ]
    if not methods:
        return []  # a Test*-named helper (e.g. a view class), not a test class

    class_skip = getattr(cls, TEST_SKIP_ATTRIBUTE, None)
    class_tags = tuple(getattr(cls, TEST_TAGS_ATTRIBUTE, ()))

    tests = []
    for name, method in methods:

        def make_call(cls: type = cls, method_name: str = name) -> Callable:
            def call(*args: object) -> object:
                instance = cls()
                return getattr(instance, method_name)(*args)

            return call

        tests.extend(
            _expand(
                method,
                base_id=f"{relative}::{cls.__name__}::{name}",
                call=make_call(),
                extra_tags=class_tags,
                class_skip=class_skip,
            )
        )
    return tests


def _expand(
    func: types.FunctionType,
    *,
    base_id: str,
    call: Callable | None = None,
    extra_tags: tuple[str, ...] = (),
    class_skip: str | None = None,
) -> list[CollectedTest]:
    """Expand @cases into one CollectedTest per case."""
    run = call if call is not None else func
    tags = (*extra_tags, *getattr(func, TEST_TAGS_ATTRIBUTE, ()))
    skip_reason = getattr(func, TEST_SKIP_ATTRIBUTE, None) or class_skip
    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)

    if case_list is None:
        return [
            CollectedTest(
                id=base_id,
                func=run,
                tags=tags,
                skip_reason=skip_reason,
            )
        ]

    return [
        CollectedTest(
            id=f"{base_id}[{index}]",
            func=functools.partial(run, *case),
            tags=tags,
            skip_reason=skip_reason,
        )
        for index, case in enumerate(case_list)
    ]


def _import_test_module(path: Path, *, root: Path) -> types.ModuleType:
    if path.is_relative_to(root):
        relative = path.relative_to(root)
        module_name = "plain_tests." + ".".join(relative.with_suffix("").parts)
    else:
        module_name = f"plain_tests.{path.stem}"

    if module_name in sys.modules:
        return sys.modules[module_name]

    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
        tree = rewrite_asserts(tree)
        # dont_inherit: the test module must NOT inherit this file's own
        # __future__ flags (inheriting `annotations` would silently turn the
        # test module's annotations into strings). Its own __future__
        # statements in the tree still apply.
        code = compile(tree, str(path), "exec", dont_inherit=True)

        module = types.ModuleType(module_name)
        module.__file__ = str(path)
        sys.modules[module_name] = module
        exec(code, module.__dict__)
    except Exception as e:
        sys.modules.pop(module_name, None)
        raise CollectionError(path, e) from e

    return module
