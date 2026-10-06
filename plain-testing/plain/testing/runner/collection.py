"""
Test collection.

Conventions: files named `test_*.py` (searched recursively from the target),
and in them functions named `test_*`. A test is a function, and a file is
the group. Test modules get assertion rewriting when imported; helper
modules do not.

Nothing that looks like a test is left out without a word. What can't be
run as it is written (a test that takes parameters nothing passes in, one
that yields, a class with tests in it, a test imported from another file)
is a collection error for its file, which says what to write instead.

Helper modules are imported by their path from one directory, the helper
directory. The caller puts it on `sys.path` before collecting. A test module
can't reach them any other way: see `loading.import_problems`.

Tests aren't kept in the application. A test file that is in it is not run,
and the run says so: `problems.tests_are_not_kept_in_the_application`.
"""

import ast
import functools
import inspect
import os
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..decorators import (
    TEST_CASES_ATTRIBUTE,
    TEST_SKIP_ATTRIBUTE,
    TEST_TAGS_ATTRIBUTE,
)
from ..definition import TestDefinitionError
from ..lifecycle import CollectedTest
from .layout import Layout, find_tests_directory
from .loading import ImportsAnotherWay, load_test_module
from .output_capture import NO_OUTPUT, OutputCapture
from .problems import (
    A_TEST_TAKES_ONLY_ITS_CASES,
    CantBeRunAsWritten,
    ProblemsInAFile,
    tests_are_not_kept_in_the_application,
)
from .targets import TargetError, name_of_the_test_at, read_target

__all__ = []

_SKIP_DIR_NAMES = {"__pycache__", "node_modules"}


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
        # The parameters of the file's tests that nothing passes in, and how
        # many of its tests take each. The run adds them up.
        self.parameters: dict[str, int] = {}
        super().__init__(f"Failed to collect {path}: {error!r}")


@dataclass(frozen=True, kw_only=True)
class RunnableTest(CollectedTest):
    """A collected test, with what the runner needs to run it."""

    func: Callable  # zero-argument callable that runs the test body
    skip_reason: str | None = None  # from `@skip`
    # The test as the test file defined it. `func` calls it, with a case's
    # values. A failure is traced back to the frame that ran this function's
    # code.
    function: types.FunctionType | None = None


def collect_tests(
    targets: list[str],
    *,
    root: Path | None = None,
    application_directory: Path | None = None,
    helper_directory: Path | None = None,
    capture: OutputCapture | None = None,
) -> tuple[list[RunnableTest], list[CollectionError]]:
    """
    Collect tests from the given targets (directories, files, a test by
    `path::name`, or the test at `path:line`), relative to `root` (default:
    cwd). A target that can't be used raises `TargetError`.

    `application_directory` is where the application is, when there is one.
    Tests aren't kept in it. A test file the search comes to there, or a
    target that is in it, is not run, and the run has a collection error that
    says which files and where they belong.

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
    """
    root = (root or Path.cwd()).resolve()
    layout = Layout(
        root=root,
        helper_directory=(helper_directory or root).resolve(),
        refused_import_name=helper_directory.name if helper_directory else None,
    )
    if application_directory is not None:
        application_directory = application_directory.resolve()
    kept_in_the_application: list[Path] = []

    # Every target is found before anything is loaded, so a target that
    # isn't there stops the run before a test file has been run.
    files_of_targets: list[tuple[list[Path], str]] = []
    for written in targets or ["."]:
        target = read_target(written)
        base = (root / target.path).resolve() if target.path not in ("", ".") else root
        name_part = target.name

        if application_directory is not None and base.is_relative_to(
            application_directory
        ):
            # Named, and not run for being named. A test that runs only when
            # it is asked for by name is one a plain `plain test` leaves out.
            if base.is_file():
                kept_in_the_application.append(base)
            elif base.is_dir():
                kept_in_the_application.extend(_test_files_kept_in(base))
            else:
                raise TargetError(f"No such test target: {written}")
            continue

        if base.is_file():
            files = [base]
            if target.line is not None:
                # None for a file that can't be read, which has an error of
                # its own to report.
                name_part = (
                    name_of_the_test_at(base, line=target.line, written=written) or ""
                )
        elif base.is_dir() and target.line is None:
            files = _find_test_files(base, leaving_out=application_directory)
            if (
                application_directory is not None
                and application_directory.is_relative_to(base)
            ):
                kept_in_the_application.extend(
                    _test_files_kept_in(application_directory)
                )
        elif base.is_dir():
            raise TargetError(
                f"No test at {written}: {target.path} is a directory, and a"
                " line is a line of a file."
            )
        else:
            raise TargetError(f"No such test target: {written}")
        files_of_targets.append((files, name_part))

    errors: list[CollectionError] = []
    if application_directory is not None and kept_in_the_application:
        tests_directory = find_tests_directory(root)
        # First: it is about where the run's tests are, not about one file.
        errors.append(
            CollectionError(
                application_directory,
                TestDefinitionError(
                    tests_are_not_kept_in_the_application(
                        _once_each_as_shown(kept_in_the_application, layout=layout),
                        application=layout.shown(application_directory),
                        tests=(
                            None
                            if tests_directory == root
                            else layout.shown(tests_directory)
                        ),
                    )
                ),
            )
        )

    collected: list[RunnableTest] = []
    for files, name_part in files_of_targets:
        for file in files:
            if capture is not None:
                capture.discard()
            try:
                tests = _collect_file(file, layout=layout)
            except CollectionError as error:
                if capture is not None:
                    error.output = capture.take()
                errors.append(error)
                continue
            if name_part:
                tests = [t for t in tests if _matches_target(t.name, name_part)]
            collected.extend(tests)

    _say_each_thing_once(errors, layout=layout)

    # De-duplicate (overlapping targets) while preserving order.
    seen: set[str] = set()
    unique = []
    for test in collected:
        if test.id not in seen:
            seen.add(test.id)
            unique.append(test)
    return unique, errors


def _say_each_thing_once(errors: list[CollectionError], *, layout: Layout) -> None:
    """
    Say what is wrong with each file that is written in a way that can't be
    run, and say why once.

    A file's error has what is wrong with that file: the imports it can't
    use, the tests it defines wrongly. Eighty files whose tests take
    parameters have one thing to be told between them. The first says it,
    and the rest say where the first is.
    """
    written_wrongly = [
        error
        for error in errors
        if isinstance(error.error, ImportsAnotherWay | CantBeRunAsWritten)
    ]
    importing_another_way = [
        e for e in written_wrongly if isinstance(e.error, ImportsAnotherWay)
    ]
    taking_parameters = [
        e
        for e in written_wrongly
        if e.error.tests.tests_taking_parameters  # ty: ignore[unresolved-attribute]
    ]

    for error in written_wrongly:
        cause = error.error
        assert isinstance(cause, ImportsAnotherWay | CantBeRunAsWritten)
        sections = []

        if isinstance(cause, ImportsAnotherWay):
            sections.append(cause.what_is_wrong())

        if cause.tests:
            sections.append(cause.tests.what_is_wrong())
        if error in taking_parameters:
            first = taking_parameters[0]
            if error is first:
                sections.append(A_TEST_TAKES_ONLY_ITS_CASES)
            else:
                sections.append(
                    "What to write instead is in the error for "
                    f"{layout.shown(first.path)}."
                )

        if isinstance(cause, ImportsAnotherWay) and error is importing_another_way[0]:
            sections.append(cause.why)

        error.parameters = dict(cause.tests.parameters)

        # Handed on as the one kind of error there is, not as the kind made
        # here to keep what was known.
        error.error = TestDefinitionError("\n\n".join(sections), line=cause.line)


def _matches_target(name: str, target: str) -> bool:
    """Whether a test name matches a `::`-target: exact, or a case of it."""
    return name == target or name.startswith(f"{target}[")


def _find_test_files(directory: Path, *, leaving_out: Path | None = None) -> list[Path]:
    """
    The files named `test_*.py` under a directory.

    Not looked in: directories whose name starts with a dot, `node_modules`
    and `__pycache__`, where nobody keeps tests, and `leaving_out`, which is
    the application.
    """
    files = []
    for dirpath, dirnames, filenames in os.walk(directory):
        # Prune skipped directories in place so os.walk never descends into
        # them (rglob can't prune — a .venv or node_modules would get a full
        # tree walk).
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES
            and not d.startswith(".")
            and Path(dirpath, d) != leaving_out
        )
        files.extend(
            Path(dirpath) / f
            for f in sorted(filenames)
            if f.startswith("test_") and f.endswith(".py")
        )
    return files


def _test_files_kept_in(directory: Path) -> list[Path]:
    """
    The test files in a directory of the application: the ones named
    `test_*.py` that have tests in them. An application can have a module
    called `test_connection.py` that checks a connection and tests nothing.
    """
    return [file for file in _find_test_files(directory) if _has_tests_in_it(file)]


def _has_tests_in_it(file: Path) -> bool:
    """
    Whether a file defines a test, as far as reading it can tell: a
    function named `test_*`, or a class with one in it. A file that can't be
    read as Python is taken to, since its name says it is a test file and
    nothing says it isn't.
    """
    try:
        tree = ast.parse(file.read_text(), filename=str(file))
    except SyntaxError, UnicodeDecodeError, OSError:
        return True

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            defined = node.body
        else:
            defined = [node]
        for member in defined:
            is_a_function = isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            if is_a_function and member.name.startswith("test_"):
                return True
    return False


def _once_each_as_shown(files: list[Path], *, layout: Layout) -> list[str]:
    shown = []
    for file in files:
        name = layout.shown(file)
        if name not in shown:
            shown.append(name)
    return shown


def _collect_file(path: Path, *, layout: Layout) -> list[RunnableTest]:
    module = _import_test_module(path, layout=layout)
    relative = layout.shown(path)

    tests: list[RunnableTest] = []
    # Every test the file defines wrongly is reported together, so a file
    # that needs the same fix twenty times says so once.
    problems = ProblemsInAFile()

    # Only functions and classes are ever looked at. Anything else in the
    # module's namespace is left alone entirely — a test module can hold
    # objects that object to being probed for attributes.
    named = [
        (name, obj)
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) or inspect.isclass(obj)
    ]

    for name, obj in named:
        defined_here = obj.__module__ == module.__name__

        if inspect.isfunction(obj):
            if not name.startswith("test_"):
                continue
            if not defined_here:
                problems.defined_elsewhere.append((name, obj.__module__))
                continue
            _check_a_test(obj, name=name, problems=problems)
            tests.extend(_expand(obj, base_id=f"{relative}::{name}"))
            continue

        # A class the file defines, with tests in it. One that was imported
        # is someone else's class, and what it holds was never going to be
        # run by this file.
        tests_in_it = _tests_defined_in(obj)
        if defined_here and tests_in_it:
            line = getattr(obj, "__firstlineno__", None)
            problems.classes_with_tests.append((line, name, len(tests_in_it)))

    if problems:
        raise CollectionError(path, CantBeRunAsWritten(problems))

    return tests


def _tests_defined_in(cls: type) -> list[str]:
    """The names of the tests a class's own body defines."""
    return [
        name
        for name, obj in vars(cls).items()
        if name.startswith("test_")
        and (inspect.isfunction(obj) or isinstance(obj, staticmethod | classmethod))
    ]


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
    func: types.FunctionType, *, name: str, problems: ProblemsInAFile
) -> None:
    """
    Add what is wrong with how one test is written: it yields, it takes
    parameters nothing passes in, or its @cases don't fit them.
    """
    if _yields(func):
        problems.tests_that_yield.append(name)
        return

    # follow_wrapped=False: a decorator that passes arguments in itself
    # (`@mock.patch(...)`) wraps the test in a function that takes anything,
    # and that wrapper is what the runner calls.
    signature = inspect.signature(func, follow_wrapped=False)
    parameters = list(signature.parameters.values())
    written = f"{name}({', '.join(str(parameter) for parameter in parameters)})"

    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)
    if case_list is None:
        try:
            signature.bind()
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
            signature.bind(*values)
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


def _expand(func: types.FunctionType, *, base_id: str) -> list[RunnableTest]:
    """Expand @cases into one test per case."""
    tags = tuple(getattr(func, TEST_TAGS_ATTRIBUTE, ()))
    skip_reason = getattr(func, TEST_SKIP_ATTRIBUTE, None)
    case_list = getattr(func, TEST_CASES_ATTRIBUTE, None)

    if case_list is None:
        return [
            RunnableTest(
                id=base_id,
                func=func,
                tags=tags,
                skip_reason=skip_reason,
                function=func,
            )
        ]

    return [
        RunnableTest(
            id=f"{base_id}[{case_id}]",
            func=functools.partial(func, *values),
            tags=tags,
            skip_reason=skip_reason,
            function=func,
        )
        for values, case_id in case_list
    ]


def _import_test_module(path: Path, *, layout: Layout) -> types.ModuleType:
    try:
        return load_test_module(path, layout=layout)
    except (ImportsAnotherWay, CantBeRunAsWritten) as e:
        raise CollectionError(path, e) from e
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
    frame = error.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_filename == str(path):
            line = frame.tb_lineno
        frame = frame.tb_next
    if line is None:
        return error
    return TestDefinitionError(f"line {line}: {error}", line=line)
