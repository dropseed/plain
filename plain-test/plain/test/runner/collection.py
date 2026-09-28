"""
Test collection.

Conventions: files named `test_*.py` (searched recursively from the target),
functions named `test_*`, and classes named `Test*` containing `test_*`
methods (a fresh instance per test). Test modules get assertion rewriting
when imported; helper modules do not.

Helper modules are imported by their bare name from one directory, the
helper directory. The caller puts it on `sys.path` before collecting. A test
module can't reach them any other way: see `loading.import_problems`.
"""

import ast
import functools
import inspect
import os
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ..decorators import (
    TEST_CASES_ATTRIBUTE,
    TEST_SKIP_ATTRIBUTE,
    TEST_TAGS_ATTRIBUTE,
)
from ..definition import TestDefinitionError
from ..lifecycle import CollectedTest
from .layout import Layout
from .loading import load_test_module

__all__ = []

_SKIP_DIR_NAMES = {"__pycache__", "node_modules"}

_CONFTEST_FILE_NAME = "conftest.py"


class CollectionError(Exception):
    """
    One file the runner couldn't collect from, and why. The cause is a
    TestDefinitionError when the file is written in a way the runner can't
    run, and whatever was raised (an ImportError, a SyntaxError) when the
    file couldn't be loaded at all.
    """

    def __init__(self, path: Path, error: BaseException) -> None:
        self.path = path
        self.error = error
        super().__init__(f"Failed to collect {path}: {error!r}")


_NO_FIXTURES_ADVICE = (
    "There are no fixtures: nothing is passed to a test by name. A test gets\n"
    "what it needs in its body, by calling a helper or entering a `with`\n"
    "block, and takes values only from @cases(...)."
)


@dataclass(frozen=True, kw_only=True)
class RunnableTest(CollectedTest):
    """A collected test, with what the runner needs to run it."""

    func: Callable  # zero-argument callable that runs the test body
    skip_reason: str | None = None  # from `@skip`


def collect_tests(
    targets: list[str],
    *,
    root: Path | None = None,
    exclude_dirs: Iterable[str] = (),
    helper_directory: Path | None = None,
) -> tuple[list[RunnableTest], list[CollectionError]]:
    """
    Collect tests from the given targets (files, directories, or
    `path::test_name` ids), relative to `root` (default: cwd).

    `exclude_dirs` adds directory names to skip during discovery (e.g. the
    runner excludes the Plain `app` directory in app mode).

    `helper_directory` is the tests directory, where helper modules live. A
    test module imports `<helper_directory>/helpers.py` as `helpers`, and is
    refused an import that goes through the directory's own name. Without
    one, helper modules are found from `root` and no import is refused for
    its name, since `root` can be called anything. Either way the caller has
    already put that directory on `sys.path`.

    Returns the collected tests plus any per-file collection errors — one
    unimportable file shouldn't stop every other file's tests from running.
    """
    root = (root or Path.cwd()).resolve()
    layout = Layout(
        root=root,
        helper_directory=(helper_directory or root).resolve(),
        refused_import_name=helper_directory.name if helper_directory else None,
    )
    skip_dir_names = _SKIP_DIR_NAMES | set(exclude_dirs)

    collected: list[RunnableTest] = []
    errors: list[CollectionError] = []
    conftest_files: list[Path] = []
    for target in targets or ["."]:
        path_part, _, name_part = target.partition("::")
        base = (root / path_part).resolve() if path_part not in ("", ".") else root

        if base.is_file():
            files = [base]
            conftest_files.extend(_conftest_files_above(base, root=root))
        elif base.is_dir():
            files, conftest_files_found = _find_test_and_conftest_files(
                base, skip_dir_names=skip_dir_names
            )
            conftest_files.extend(conftest_files_found)
        else:
            raise FileNotFoundError(f"No such test target: {target}")

        for file in files:
            try:
                tests = _collect_file(file, layout=layout)
            except CollectionError as error:
                errors.append(error)
                continue
            if name_part:
                tests = [t for t in tests if _matches_target(t.name, name_part)]
            collected.extend(tests)

    # Overlapping targets find the same file twice.
    for conftest_file in dict.fromkeys(conftest_files):
        errors.append(
            CollectionError(
                conftest_file,
                TestDefinitionError(_conftest_message(conftest_file, layout=layout)),
            )
        )

    # De-duplicate (overlapping targets) while preserving order.
    seen: set[str] = set()
    unique = []
    for test in collected:
        if test.id not in seen:
            seen.add(test.id)
            unique.append(test)
    return unique, errors


def _matches_target(name: str, target: str) -> bool:
    """Whether a test name matches a `::`-target: exact, a case of it, or a
    test within the targeted class."""
    return name == target or name.startswith((f"{target}[", f"{target}::"))


def _find_test_and_conftest_files(
    directory: Path, *, skip_dir_names: set[str]
) -> tuple[list[Path], list[Path]]:
    """The test files under a directory, and the conftest files among them."""
    test_files = []
    conftest_files = []
    for dirpath, dirnames, filenames in os.walk(directory):
        # Prune skipped directories in place so os.walk never descends into
        # them (rglob can't prune — a .venv or node_modules would get a full
        # tree walk).
        dirnames[:] = sorted(
            d for d in dirnames if d not in skip_dir_names and not d.startswith(".")
        )
        test_files.extend(
            Path(dirpath) / f
            for f in sorted(filenames)
            if f.startswith("test_") and f.endswith(".py")
        )
        if _CONFTEST_FILE_NAME in filenames:
            conftest_files.append(Path(dirpath) / _CONFTEST_FILE_NAME)
    return test_files, conftest_files


def _conftest_files_above(test_file: Path, *, root: Path) -> list[Path]:
    """
    The conftest files that would have applied to one test file: its own
    directory's, and each directory's above it up to the root.
    """
    if not test_file.is_relative_to(root):
        directories = [test_file.parent]
    else:
        directories = [
            directory
            for directory in (test_file.parent, *test_file.parent.parents)
            if directory.is_relative_to(root)
        ]
    return [
        directory / _CONFTEST_FILE_NAME
        for directory in reversed(directories)
        if (directory / _CONFTEST_FILE_NAME).is_file()
    ]


def _conftest_message(path: Path, *, layout: Layout) -> str:
    fixtures, autouse_fixtures = _fixture_names(path)
    helpers_file = layout.shown(layout.helper_directory / "helpers.py")
    lifecycle_file = layout.shown(layout.helper_directory / "lifecycle.py")

    lines = [
        "conftest.py is a pytest file, and nothing reads it here. There are no",
        "fixtures: nothing in this file runs, and nothing is passed to a test",
        "by name. Move what it holds, then delete the file.",
        "",
        "- A fixture that tests ask for becomes a function in a helper module,",
        f"  such as {helpers_file}. A test imports it",
        "  (`from helpers import create_user`) and calls it in its body. A",
        "  fixture that cleans up after itself becomes a `@contextmanager`",
        "  that the test enters with `with`.",
        "- A fixture that protected every test without being asked for",
        "  (`autouse=True`) becomes a TestLifecycle's `around_test()`, in",
        f"  {lifecycle_file}.",
        "- Hooks (`pytest_configure`, `pytest_collection_modifyitems`, ...)",
        "  have no equivalent.",
    ]
    if fixtures:
        lines += ["", f"Fixtures in this file: {', '.join(fixtures)}"]
    if autouse_fixtures:
        lines += ["", f"Autouse fixtures in this file: {', '.join(autouse_fixtures)}"]
    return "\n".join(lines)


def _fixture_names(path: Path) -> tuple[list[str], list[str]]:
    """
    The fixtures a conftest defines, as (asked for by name, autouse). Read
    from its syntax, since importing it would need pytest.
    """
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError, UnicodeDecodeError:
        return [], []

    fixtures = []
    autouse_fixtures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            written = ast.unparse(decorator)
            if "fixture" not in written:
                continue
            if "autouse=True" in written:
                autouse_fixtures.append(node.name)
            else:
                fixtures.append(node.name)
            break
    return fixtures, autouse_fixtures


def _collect_file(path: Path, *, layout: Layout) -> list[RunnableTest]:
    module = _import_test_module(path, layout=layout)
    relative = layout.shown(path)

    tests: list[RunnableTest] = []
    # Every test the file defines wrongly is reported together, so a file
    # that needs the same fix twenty times says so once.
    problems: list[str] = []
    for name, obj in vars(module).items():
        # Only functions and classes are ever tests. Anything else in the
        # module's namespace is left alone entirely — a test module can hold
        # objects that object to being probed for attributes.
        if not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        if obj.__module__ != module.__name__:
            continue  # imported, not defined here

        if inspect.isfunction(obj) and name.startswith("test_"):
            problems.extend(_argument_problems(obj, name=name, is_method=False))
            tests.extend(_expand(obj, base_id=f"{relative}::{name}"))
        elif inspect.isclass(obj) and name.startswith("Test"):
            tests.extend(_collect_class(obj, relative=relative, problems=problems))

    if problems:
        listed = "\n".join(f"  {problem}" for problem in problems)
        error = TestDefinitionError(
            f"These tests can't be run as written:\n\n{listed}\n\n{_NO_FIXTURES_ADVICE}"
        )
        raise CollectionError(path, error)

    return tests


def _argument_problems(
    func: types.FunctionType, *, name: str, is_method: bool
) -> list[str]:
    """
    What is wrong with how a test's parameters get their values: parameters
    nothing passes in, or @cases that don't fit them.
    """
    # follow_wrapped=False: a decorator that passes arguments in itself
    # (`@mock.patch(...)`) wraps the test in a function that takes anything,
    # and that wrapper is what the runner calls.
    signature = inspect.signature(func, follow_wrapped=False)
    # A method is called on a fresh instance, which fills its first parameter.
    instance = (object(),) if is_method else ()
    if is_method and not signature.parameters:
        return [f"{name}() is a method, and has no `self` parameter."]
    parameters = list(signature.parameters.values())[len(instance) :]
    written = f"{name}({', '.join(str(parameter) for parameter in parameters)})"

    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)
    if case_list is None:
        try:
            signature.bind(*instance)
        except TypeError:
            return [f"{written} takes parameters, and nothing passes them in."]
        return []

    problems = []
    for index, (values, case_id) in enumerate(case_list):
        try:
            signature.bind(*instance, *values)
        except TypeError:
            label = case_id if case_id is not None else index
            count = "1 value" if len(values) == 1 else f"{len(values)} values"
            problems.append(
                f"{written} doesn't fit its @cases: case [{label}] passes {count}."
            )
    return problems


def _collect_class(
    cls: type, *, relative: str, problems: list[str]
) -> list[RunnableTest]:
    # Walk the MRO base-first so inherited test methods are collected too,
    # with subclass overrides replacing the base definition in place.
    methods_by_name: dict[str, types.FunctionType] = {}
    for klass in reversed(cls.__mro__):
        for name, obj in vars(klass).items():
            if inspect.isfunction(obj) and name.startswith("test_"):
                methods_by_name[name] = obj
    methods = list(methods_by_name.items())
    if not methods:
        return []  # a Test*-named helper (e.g. a view class), not a test class

    class_skip = getattr(cls, TEST_SKIP_ATTRIBUTE, None)
    class_tags = tuple(getattr(cls, TEST_TAGS_ATTRIBUTE, ()))

    tests = []
    for name, method in methods:
        problems.extend(
            _argument_problems(method, name=f"{cls.__name__}::{name}", is_method=True)
        )

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
) -> list[RunnableTest]:
    """Expand @cases into one test per case."""
    run = call if call is not None else func
    tags = (*extra_tags, *getattr(func, TEST_TAGS_ATTRIBUTE, ()))
    skip_reason = getattr(func, TEST_SKIP_ATTRIBUTE, None) or class_skip
    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)

    if case_list is None:
        return [
            RunnableTest(
                id=base_id,
                func=run,
                tags=tags,
                skip_reason=skip_reason,
            )
        ]

    return [
        RunnableTest(
            id=f"{base_id}[{case_id if case_id is not None else index}]",
            func=functools.partial(run, *values),
            tags=tags,
            skip_reason=skip_reason,
        )
        for index, (values, case_id) in enumerate(case_list)
    ]


def _import_test_module(path: Path, *, layout: Layout) -> types.ModuleType:
    try:
        return load_test_module(path, layout=layout)
    except TestDefinitionError as e:
        raise CollectionError(path, _with_its_line(e, path=path)) from e
    except Exception as e:
        raise CollectionError(path, e) from e


def _with_its_line(error: TestDefinitionError, *, path: Path) -> TestDefinitionError:
    """
    A definition error raised while the test file ran, such as a `@skip` with
    no reason, with the line of the file that raised it in front. The
    message is all that gets printed, and "@skip requires a reason" doesn't
    say which of a file's tests it means.
    """
    line = None
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_filename == str(path):
            line = traceback.tb_lineno
        traceback = traceback.tb_next
    if line is None:
        return error
    return TestDefinitionError(f"line {line}: {error}")
