"""
Test collection.

Conventions: files named `test_*.py` (searched recursively from the target),
functions named `test_*`, and classes named `Test*` containing `test_*`
methods (a fresh instance per test). Test modules get assertion rewriting
when imported; helper modules do not.

Nothing that looks like a test is left out without a word. What can't be
run as it is written (a test that takes fixtures, one that yields, a
`unittest.TestCase`, a test imported from another file) is a collection
error for its file, which says what to write instead.

Helper modules are imported by their bare name from one directory, the
helper directory. The caller puts it on `sys.path` before collecting. A test
module can't reach them any other way: see `loading.import_problems`.
"""

import ast
import functools
import inspect
import os
import traceback
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
from .loading import (
    ImportsAnotherWay,
    ImportsPytest,
    PytestImport,
    is_pytest,
    load_test_module,
    what_replaces_pytest,
)
from .output_capture import NO_OUTPUT, OutputCapture
from .problems import NO_FIXTURES_ADVICE, CantBeRunAsWritten, ProblemsInAFile

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
        # What loading the file wrote, when the run is holding output.
        self.output = NO_OUTPUT
        super().__init__(f"Failed to collect {path}: {error!r}")


@dataclass(frozen=True, kw_only=True)
class RunnableTest(CollectedTest):
    """A collected test, with what the runner needs to run it."""

    func: Callable  # zero-argument callable that runs the test body
    skip_reason: str | None = None  # from `@skip`
    # The test as the test file defined it. `func` calls it, with a case's
    # values or on a fresh instance of its class. A failure is traced back
    # to the frame that ran this function's code.
    function: types.FunctionType | None = None


def collect_tests(
    targets: list[str],
    *,
    root: Path | None = None,
    exclude_dirs: Iterable[str] = (),
    helper_directory: Path | None = None,
    capture: OutputCapture | None = None,
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

    `capture` is the run's hold on what is written to stdout and stderr. What
    loading a file writes is kept with that file's error, and thrown away
    when the file loads.

    Returns the collected tests plus any per-file collection errors — one
    unimportable file shouldn't stop every other file's tests from running.
    A `conftest.py` comes first among the errors: it is where the fixtures
    the other files ask for were, so what it says explains what they say.
    """
    root = (root or Path.cwd()).resolve()
    layout = Layout(
        root=root,
        helper_directory=(helper_directory or root).resolve(),
        refused_import_name=helper_directory.name if helper_directory else None,
    )
    skip_dir_names = _SKIP_DIR_NAMES | set(exclude_dirs)

    # Everything is found before anything is loaded, so that a test file is
    # read knowing which conftest files there are.
    files_of_targets: list[tuple[list[Path], str]] = []
    conftest_files: list[Path] = []
    for target in targets or ["."]:
        path_part, _, name_part = target.partition("::")
        base = (root / path_part).resolve() if path_part not in ("", ".") else root

        # The ones above the target apply to it whichever way it is
        # written: as a file, a directory, or one test in a file.
        conftest_files.extend(_conftest_files_above(base, root=root))
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files, conftest_files_found = _find_test_and_conftest_files(
                base, skip_dir_names=skip_dir_names
            )
            conftest_files.extend(conftest_files_found)
        else:
            raise FileNotFoundError(f"No such test target: {target}")
        files_of_targets.append((files, name_part))

    # Overlapping targets find the same file twice.
    conftest_files = list(dict.fromkeys(conftest_files))
    fixtures_in_conftests: dict[str, str] = {}
    errors: list[CollectionError] = []
    for conftest_file in conftest_files:
        fixtures, autouse_fixtures = _fixture_names(conftest_file)
        shown = layout.shown(conftest_file)
        for name in fixtures:
            fixtures_in_conftests.setdefault(name, f"a fixture in {shown}")
        for name in autouse_fixtures:
            fixtures_in_conftests.setdefault(name, f"an autouse fixture in {shown}")
        message = _conftest_message(
            fixtures=fixtures, autouse_fixtures=autouse_fixtures, layout=layout
        )
        errors.append(CollectionError(conftest_file, TestDefinitionError(message)))

    collected: list[RunnableTest] = []
    for files, name_part in files_of_targets:
        for file in files:
            if capture is not None:
                capture.discard()
            try:
                tests = _collect_file(
                    file, layout=layout, fixtures_in_conftests=fixtures_in_conftests
                )
            except CollectionError as error:
                if capture is not None:
                    error.output = capture.take()
                errors.append(error)
                continue
            if name_part:
                tests = [t for t in tests if _matches_target(t.name, name_part)]
            collected.extend(tests)

    _say_each_thing_once(
        errors, layout=layout, fixtures_in_conftests=fixtures_in_conftests
    )

    # De-duplicate (overlapping targets) while preserving order.
    seen: set[str] = set()
    unique = []
    for test in collected:
        if test.id not in seen:
            seen.add(test.id)
            unique.append(test)
    return unique, errors


def _say_each_thing_once(
    errors: list[CollectionError],
    *,
    layout: Layout,
    fixtures_in_conftests: dict[str, str],
) -> None:
    """
    Say what is wrong with each file that is written in a way that can't be
    run, and say why once.

    A file's error has what is wrong with that file: the pytest it imports,
    the imports it can't use, the tests it defines wrongly. Eighty files
    that import pytest, or ask for fixtures, have one thing to be told
    between them. The first says it, and the rest say where the first is.
    """
    written_wrongly = [
        error
        for error in errors
        if isinstance(
            error.error, ImportsPytest | ImportsAnotherWay | CantBeRunAsWritten
        )
    ]

    importing_pytest = [
        e for e in written_wrongly if isinstance(e.error, ImportsPytest)
    ]
    pytest_uses: dict[str, int] = {}
    for error in importing_pytest:
        assert isinstance(error.error, ImportsPytest)
        for name, count in error.error.uses.items():
            pytest_uses[name] = pytest_uses.get(name, 0) + count
    pytest_uses = dict(sorted(pytest_uses.items(), key=lambda item: -item[1]))

    importing_another_way = [
        e for e in written_wrongly if isinstance(e.error, ImportsAnotherWay)
    ]
    asking_for_fixtures = [
        e
        for e in written_wrongly
        if e.error.tests.tests_taking_parameters  # ty: ignore[unresolved-attribute]
    ]
    # A conftest's error says there are no fixtures, and where each kind
    # goes, and each file names the conftest its fixtures were in.
    a_conftest_says_it = any(e.path.name == _CONFTEST_FILE_NAME for e in errors)

    for error in written_wrongly:
        cause = error.error
        assert isinstance(cause, ImportsPytest | ImportsAnotherWay | CantBeRunAsWritten)
        sections = []

        if isinstance(cause, ImportsPytest):
            first = importing_pytest[0]
            sections.append(
                cause.what_this_file_does(
                    explained_for=None if error is first else layout.shown(first.path)
                )
            )
        if isinstance(cause, ImportsAnotherWay):
            sections.append(cause.what_is_wrong())

        if cause.tests:
            sections.append(
                cause.tests.what_is_wrong(fixtures_in_conftests=fixtures_in_conftests)
            )
        if error in asking_for_fixtures and not a_conftest_says_it:
            first = asking_for_fixtures[0]
            if error is first:
                sections.append(NO_FIXTURES_ADVICE)
            else:
                sections.append(
                    "What to write instead is in the error for "
                    f"{layout.shown(first.path)}."
                )

        if isinstance(cause, ImportsAnotherWay) and error is importing_another_way[0]:
            sections.append(cause.why)
        if isinstance(cause, ImportsPytest) and error is importing_pytest[0]:
            used_by = "this file" if len(importing_pytest) == 1 else "these files"
            sections.append(
                what_replaces_pytest(pytest_uses, layout=layout, used_by=used_by)
            )

        # Handed on as the one kind of error there is, not as the kind made
        # here to keep what was known.
        error.error = TestDefinitionError("\n\n".join(sections), line=cause.line)


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


def _conftest_files_above(target: Path, *, root: Path) -> list[Path]:
    """
    The conftest files that would have applied to everything in a target:
    the ones in each directory above it, up to the root, and for a file the
    one beside it. A directory's own, and the ones below it, are found when
    it is searched.
    """
    nearest = target.parent
    if not nearest.is_relative_to(root):
        # A directory has nothing above it to look in. A file has the
        # directory it is in, which nothing else will search.
        directories = [nearest] if target.is_file() else []
    else:
        directories = [
            directory
            for directory in (nearest, *nearest.parents)
            if directory.is_relative_to(root)
        ]
    return [
        directory / _CONFTEST_FILE_NAME
        for directory in reversed(directories)
        if (directory / _CONFTEST_FILE_NAME).is_file()
    ]


def _conftest_message(
    *, fixtures: list[str], autouse_fixtures: list[str], layout: Layout
) -> str:
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


def _collect_file(
    path: Path, *, layout: Layout, fixtures_in_conftests: dict[str, str]
) -> list[RunnableTest]:
    module = _import_test_module(path, layout=layout)
    relative = layout.shown(path)

    tests: list[RunnableTest] = []
    # Every test the file defines wrongly is reported together, so a file
    # that needs the same fix twenty times says so once.
    problems = ProblemsInAFile()

    # Only functions and classes are ever tests. Anything else in the
    # module's namespace is left alone entirely — a test module can hold
    # objects that object to being probed for attributes.
    named = [
        (name, obj)
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) or inspect.isclass(obj)
    ]
    classes_defined_here = [
        obj
        for _, obj in named
        if inspect.isclass(obj) and obj.__module__ == module.__name__
    ]

    for name, obj in named:
        defined_here = obj.__module__ == module.__name__

        if inspect.isfunction(obj):
            if not name.startswith("test_"):
                continue
            if not defined_here:
                problems.defined_elsewhere.append((name, obj.__module__))
                continue
            _check_a_test(obj, name=name, takes="nothing", problems=problems)
            tests.extend(_expand(obj, base_id=f"{relative}::{name}"))
            continue

        if _is_a_unittest_case(obj):
            # `TestCase` itself, imported to be a base class, is not a test.
            if defined_here:
                problems.unittest_cases.append(name)
            continue
        if not name.startswith("Test"):
            continue
        if defined_here:
            tests.extend(_collect_class(obj, relative=relative, problems=problems))
        elif _test_methods(obj) and not any(
            issubclass(cls, obj) for cls in classes_defined_here
        ):
            # A class imported to be a base class has its tests run by the
            # class that is made from it. One imported and left at that has
            # tests nothing here runs.
            problems.defined_elsewhere.append((name, obj.__module__))

    if problems:
        raise CollectionError(path, CantBeRunAsWritten(problems))

    return tests


def _is_a_unittest_case(cls: type) -> bool:
    # By name: importing unittest to ask would cost every run the import.
    return any(
        base.__module__ == "unittest.case" and base.__name__ == "TestCase"
        for base in cls.__mro__
    )


def _yields(func: types.FunctionType) -> bool:
    """Whether calling a function makes a generator and runs none of it."""
    functions = [func]
    try:
        # A decorator that uses `functools.wraps` hands back a function that
        # isn't a generator function, around one that is.
        functions.append(inspect.unwrap(func))
    except ValueError:
        pass  # wrapped in itself
    return any(
        inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function)
        for function in functions
    )


def _check_a_test(
    func: types.FunctionType,
    *,
    name: str,
    takes: str,
    problems: ProblemsInAFile,
) -> None:
    """
    Add what is wrong with how one test is written: it yields, it takes
    parameters nothing passes in, or its @cases don't fit them.

    `takes` is what calling it fills in before any values: "nothing" for a
    function and a static method, "its instance" for a method, and "its
    class" for a class method.
    """
    if _yields(func):
        problems.tests_that_yield.append(name)
        return

    # follow_wrapped=False: a decorator that passes arguments in itself
    # (`@mock.patch(...)`) wraps the test in a function that takes anything,
    # and that wrapper is what the runner calls.
    signature = inspect.signature(func, follow_wrapped=False)
    filled_in = () if takes == "nothing" else (object(),)
    if filled_in and not signature.parameters:
        what = "self" if takes == "its instance" else "cls"
        problems.of_one_test.append(
            f"{name}() is a method, and has no `{what}` parameter."
        )
        return
    parameters = list(signature.parameters.values())[len(filled_in) :]
    written = f"{name}({', '.join(str(parameter) for parameter in parameters)})"

    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)
    if case_list is None:
        try:
            signature.bind(*filled_in)
        except TypeError:
            problems.tests_taking_parameters.append(written)
            for parameter in parameters:
                if parameter.default is not inspect.Parameter.empty:
                    continue
                if parameter.kind in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    continue
                problems.parameters[parameter.name] = (
                    problems.parameters.get(parameter.name, 0) + 1
                )
        return

    for values, case_id in case_list:
        try:
            signature.bind(*filled_in, *values)
        except TypeError:
            problems.of_one_test.append(
                f"{written} doesn't fit its @cases: case [{case_id}] "
                f"{_how_a_case_misses(parameters, values)}"
            )


def _how_a_case_misses(
    parameters: list[inspect.Parameter], values: tuple[object, ...]
) -> str:
    """
    What a case passes and what that leaves: "passes 2 values, for plan
    and amount. Nothing fills currency."
    """
    count = "1 value" if len(values) == 1 else f"{len(values)} values"
    names = [
        parameter.name
        for parameter in parameters
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]

    if len(values) > len(names):
        if not names:
            return f"passes {count}, and the test takes none."
        takes = "1" if len(names) == 1 else str(len(names))
        return f"passes {count}, and the test takes {takes}: {_listed(names)}."

    filled = names[: len(values)]
    unfilled = [
        parameter.name
        for parameter in parameters
        if parameter.name not in filled
        and parameter.default is inspect.Parameter.empty
        and parameter.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    passes = f"passes {count}, for {_listed(filled)}." if filled else f"passes {count}."
    return f"{passes} Nothing fills {_listed(unfilled)}."


def _listed(names: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _test_methods(cls: type) -> dict[str, tuple[types.FunctionType, str]]:
    """
    A class's tests by name, each with what calling it fills in: "its
    instance" for a method, "its class" for a class method, and "nothing"
    for a static method.
    """
    # Walk the MRO base-first so inherited test methods are collected too,
    # with subclass overrides replacing the base definition in place.
    methods: dict[str, tuple[types.FunctionType, str]] = {}
    for klass in reversed(cls.__mro__):
        for name, obj in vars(klass).items():
            if not name.startswith("test_"):
                continue
            if inspect.isfunction(obj):
                methods[name] = (obj, "its instance")
            elif isinstance(obj, classmethod) and inspect.isfunction(obj.__func__):
                methods[name] = (obj.__func__, "its class")
            elif isinstance(obj, staticmethod) and inspect.isfunction(obj.__func__):
                methods[name] = (obj.__func__, "nothing")
    return methods


def _collect_class(
    cls: type, *, relative: str, problems: ProblemsInAFile
) -> list[RunnableTest]:
    methods = _test_methods(cls)
    if not methods:
        return []  # a Test*-named helper (e.g. a view class), not a test class

    class_skip = getattr(cls, TEST_SKIP_ATTRIBUTE, None)
    class_tags = tuple(getattr(cls, TEST_TAGS_ATTRIBUTE, ()))

    tests = []
    for name, (method, takes) in methods.items():
        _check_a_test(
            method, name=f"{cls.__name__}::{name}", takes=takes, problems=problems
        )

        def make_call(cls: type = cls, method_name: str = name) -> Callable:
            def call(*args: object) -> object:
                # On a fresh instance, whatever kind of method it is: a
                # static or a class method is called the same way.
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
                function=func,
            )
        ]

    return [
        RunnableTest(
            id=f"{base_id}[{case_id}]",
            func=functools.partial(run, *values),
            tags=tags,
            skip_reason=skip_reason,
            function=func,
        )
        for values, case_id in case_list
    ]


def _import_test_module(path: Path, *, layout: Layout) -> types.ModuleType:
    try:
        return load_test_module(path, layout=layout)
    except (ImportsPytest, ImportsAnotherWay, CantBeRunAsWritten) as e:
        raise CollectionError(path, e) from e
    except TestDefinitionError as e:
        raise CollectionError(path, _with_its_line(e, path=path)) from e
    except ModuleNotFoundError as e:
        imports_pytest = _a_helper_imports_pytest(e, layout=layout)
        raise CollectionError(path, imports_pytest or e) from e
    except Exception as e:
        raise CollectionError(path, e) from e


def _a_helper_imports_pytest(
    error: ModuleNotFoundError, *, layout: Layout
) -> ImportsPytest | None:
    """
    What to say when a module the test file imports, imports pytest. The
    test file's own import was found by reading it, before it was run.
    """
    if error.name is None or not is_pytest(error.name):
        return None
    # The last frame is the import that failed.
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return None
    importing = frames[-1]
    assert importing.lineno is not None
    return ImportsPytest(
        imported_at=PytestImport(
            line=importing.lineno,
            written=(importing.line or f"import {error.name}").strip(),
        ),
        uses={},
        other_import_problems=[],
        layout=layout,
        imported_by=layout.shown(Path(importing.filename)),
    )


def _with_its_line(error: TestDefinitionError, *, path: Path) -> TestDefinitionError:
    """
    A definition error raised while the test file ran, such as a `@skip` with
    no reason, with the line of the file that raised it in front. The
    message is all that gets printed, and "@skip requires a reason" doesn't
    say which of a file's tests it means.
    """
    line = None
    frame = error.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(path):
            line = frame.tb_lineno
        frame = frame.tb_next
    if line is None:
        return error
    return TestDefinitionError(f"line {line}: {error}", line=line)
