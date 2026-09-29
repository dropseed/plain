"""
What a failed test carries away from its failure.

A `Failure` is everything the report says about one failed test, already
printed: text, and nothing that is still alive. It is made while the test's
lifecycles are still in place and the values are as the test left them,
and then the error, its frames and everything they held are let go.

The reporter turns a `Failure` into what is printed. Anything else that
reports a run reads the same structure.
"""

import ast
import inspect
import shlex
import traceback
import types
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..definition import TestDefinitionError
from . import assertions
from .collection import CollectionError, RunnableTest
from .output_capture import NO_OUTPUT, Output, StreamOutput
from .printing import Describer, Diff, PrintedValue, ValuePrinter

__all__ = []

_RUNNER_DIRECTORY = str(Path(__file__).parent)

# The names a rewritten assert keeps values under. An assert deletes its
# own as it finishes, so these are only ever seen in a frame that an error
# left in the middle of one.
_KEPT_BY_AN_ASSERT = "__plain_test_"


@dataclass(frozen=True, kw_only=True)
class AssertedPart:
    """One part of a failed assert's expression."""

    # The part as the test file wrote it: `response.status_code`.
    source: str
    # How far inside the expression it is, from 0.
    depth: int
    # What it was. None when Python never evaluated it, as it doesn't the
    # right side of an `and` whose left side was false.
    value: PrintedValue | None


@dataclass(frozen=True, kw_only=True)
class FailedAssert:
    """The assert that failed, and the values inside it."""

    # The expression as the test file wrote it, without `assert`.
    expression: str
    # What the test gave after the comma, or None.
    message: str | None
    # The parts worth printing, outermost first, in the order written.
    parts: tuple[AssertedPart, ...]
    # For `assert left == right` with a side too large to read whole.
    diff: Diff | None


@dataclass(frozen=True, kw_only=True)
class LocalValue:
    """A name in the test function, and what it was when the test failed."""

    name: str
    value: PrintedValue


@dataclass(frozen=True, kw_only=True)
class Frame:
    """One step of a traceback."""

    # Relative to where the run started, when it is under there.
    file: str
    line: int
    function: str


@dataclass(frozen=True, kw_only=True)
class Failure:
    # "AssertionError", "KeyError"
    error_type: str
    error_message: str
    # The statement in the test function that failed, or that called what
    # failed. None when the test function isn't in the traceback: the error
    # came from a lifecycle.
    file: str | None
    line: int | None
    # Formatted, with the runner's own frames taken off the top.
    traceback: str
    # The same steps as data, outermost first. The error's own, without
    # the ones of an error it was raised from.
    frames: tuple[Frame, ...]
    # None when what failed wasn't an assert in a test file.
    failed_assert: FailedAssert | None
    # The test function's, in the order they were bound, without the ones
    # `failed_assert` has already printed.
    locals: tuple[LocalValue, ...]
    # The command that runs this test again, safe to paste.
    rerun_command: str
    # What the test wrote, from before its lifecycles entered to after they
    # exited. It is added when they have exited.
    stdout: StreamOutput = NO_OUTPUT.stdout
    stderr: StreamOutput = NO_OUTPUT.stderr


@dataclass(frozen=True, kw_only=True)
class CollectionFailure:
    """A file no tests could be collected from, and why."""

    file: str
    # Whether the file is written in a way the runner can't run. Then
    # `message` says what is wrong and what to write instead, and there is
    # no traceback. Otherwise it is an error like any other, raised while
    # the file was being loaded.
    is_definition_error: bool
    error_type: str
    message: str
    traceback: str | None
    # Where in the file, when the error says.
    line: int | None
    # What loading the file wrote.
    stdout: StreamOutput = NO_OUTPUT.stdout
    stderr: StreamOutput = NO_OUTPUT.stderr


def describe_collection_error(
    error: CollectionError, *, file: str, output: Output = NO_OUTPUT
) -> CollectionFailure:
    cause = error.error
    if isinstance(cause, TestDefinitionError):
        return CollectionFailure(
            file=file,
            is_definition_error=True,
            error_type=type(cause).__qualname__,
            message=str(cause),
            traceback=None,
            line=None,
            stdout=output.stdout,
            stderr=output.stderr,
        )

    return CollectionFailure(
        file=file,
        is_definition_error=False,
        error_type=type(cause).__qualname__,
        message=_guarded_str(cause),
        traceback=format_collection_traceback(cause),
        line=_line_in_the_file(cause, path=error.path),
        stdout=output.stdout,
        stderr=output.stderr,
    )


def format_collection_traceback(cause: BaseException) -> str:
    """
    The traceback of an error raised while a test file was being loaded,
    starting at the test file.

    The frames above the test file are the runner loading it, by way of
    `ast` or the import system. A SyntaxError has no frames below those: it
    names the file and the line itself.
    """
    not_the_test_file = (_RUNNER_DIRECTORY, ast.__file__, "<frozen importlib")
    tb = cause.__traceback__
    while tb is not None:
        if not tb.tb_frame.f_code.co_filename.startswith(not_the_test_file):
            break
        tb = tb.tb_next
    return "".join(traceback.format_exception(type(cause), cause, tb)).rstrip()


def _line_in_the_file(cause: BaseException, *, path: Path) -> int | None:
    if isinstance(cause, SyntaxError):
        return cause.lineno

    # The deepest step that is in the file itself.
    line = None
    tb = cause.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == str(path):
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def shown_path(filename: str) -> str:
    """A path the way the run's output writes it: relative to where it started."""
    path = Path(filename)
    root = Path.cwd()
    if path.is_absolute() and path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return filename


def describe_failure(
    error: BaseException,
    *,
    test: RunnableTest,
    describers: Sequence[Describer],
    full_values: bool,
) -> Failure:
    printer = ValuePrinter(describers=describers, full_values=full_values)

    failed_assert = None
    watched = assertions.watched_assert_of(error)
    if watched is not None:
        failed_assert = _failed_assert(watched, printer=printer)

    already_printed = set()
    if failed_assert is not None:
        already_printed = {part.source for part in failed_assert.parts}

    file, line = _where_in_the_test(error, test=test)
    return Failure(
        error_type=type(error).__qualname__,
        error_message=_guarded_str(error),
        file=file,
        line=line,
        traceback=format_traceback(error),
        frames=_frames(error),
        failed_assert=failed_assert,
        locals=_locals_of_the_test(
            error, test=test, printer=printer, already_printed=already_printed
        ),
        rerun_command=rerun_command(test.id),
    )


def failure_that_could_not_be_described(
    error: BaseException, *, test: RunnableTest, while_describing: Exception
) -> Failure:
    """
    The failure with its traceback and nothing more, for when describing it
    went wrong. The test's own error is what the reader came for.
    """
    file, line = _where_in_the_test(error, test=test)
    return Failure(
        error_type=type(error).__qualname__,
        error_message=_guarded_str(error),
        file=file,
        line=line,
        traceback=format_traceback(error)
        + "\n(The values couldn't be printed: "
        + f"{type(while_describing).__qualname__}: {while_describing})\n",
        frames=_frames(error),
        failed_assert=None,
        locals=(),
        rerun_command=rerun_command(test.id),
    )


def _guarded_str(error: BaseException) -> str:
    try:
        return str(error)
    except Exception as raised:
        return f"<its str raised {type(raised).__qualname__}: {raised}>"


def rerun_command(test_id: str) -> str:
    """
    The command that runs one test, safe to paste. A case id can hold
    anything (`test_price[annual plan]`), and a shell reads spaces, brackets,
    quotes and `$` for itself unless the id is quoted.
    """
    return f"plain test {shlex.quote(test_id)}"


def _without_the_runners_frames(error: BaseException) -> types.TracebackType | None:
    tb = error.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if not filename.startswith(_RUNNER_DIRECTORY) and "contextlib" not in filename:
            break
        tb = tb.tb_next
    return tb or error.__traceback__


def format_traceback(error: BaseException) -> str:
    """Format a traceback with the runner's own frames trimmed off the top."""
    return "".join(
        traceback.format_exception(
            type(error), error, _without_the_runners_frames(error)
        )
    )


def _frames(error: BaseException) -> tuple[Frame, ...]:
    frames = []
    tb = _without_the_runners_frames(error)
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(
            Frame(
                file=shown_path(code.co_filename),
                line=tb.tb_lineno,
                function=code.co_qualname,
            )
        )
        tb = tb.tb_next
    return tuple(frames)


def _where_in_the_test(
    error: BaseException, *, test: RunnableTest
) -> tuple[str | None, int | None]:
    step = _step_of_the_test(error, test=test)
    if step is None:
        return None, None
    return shown_path(step.tb_frame.f_code.co_filename), step.tb_lineno


def where_defined(test: RunnableTest) -> tuple[str, int | None]:
    """The file a test is in, and the line its definition starts on."""
    file = test.id.partition("::")[0]
    if test.function is None:
        return file, None
    return file, inspect.unwrap(test.function).__code__.co_firstlineno


def _failed_assert(
    watched: assertions.WatchedAssert, *, printer: ValuePrinter
) -> FailedAssert:
    diff = None
    diffed: tuple[int, ...] = ()
    if watched.equality is not None:
        left, right = (watched.values[index] for index in watched.equality)
        evaluated = (
            left.value is not assertions.NOT_EVALUATED
            and right.value is not assertions.NOT_EVALUATED
        )
        if evaluated:
            diff = printer.diff(
                left.value,
                right.value,
                left_source=left.source,
                right_source=right.source,
            )
            if diff is not None:
                diffed = watched.equality

    parts = []
    printed_before = set()
    # The depth of a part that wasn't evaluated, while going through the
    # parts inside it. They weren't evaluated either, and saying so of the
    # whole says it of them.
    inside_not_evaluated = None
    for index, watched_value in enumerate(watched.values):
        if inside_not_evaluated is not None:
            if watched_value.depth > inside_not_evaluated:
                continue
            inside_not_evaluated = None

        if watched_value.is_literal:
            # Its value is what is written. It was kept for the diff.
            continue
        if watched_value.value is assertions.NOT_EVALUATED:
            value = None
            inside_not_evaluated = watched_value.depth
        elif _says_only_where_it_is_from(watched_value):
            continue
        elif index in diffed:
            # The diff says what matters about it, in less.
            value = printer.summarized(watched_value.value)
        else:
            value = printer.printed(watched_value.value, name=watched_value.source)

        # `a == b or a == c` has `a` in it twice, and says it once.
        printed = (watched_value.source, value)
        if printed in printed_before:
            continue
        printed_before.add(printed)

        parts.append(
            AssertedPart(
                source=watched_value.source, depth=watched_value.depth, value=value
            )
        )

    message = None
    if watched.message is not None:
        message = _guarded_str(watched.message)

    return FailedAssert(
        expression=watched.expression,
        message=message,
        parts=tuple(parts),
        diff=diff,
    )


def _is_module_class_or_function(value: object) -> bool:
    return (
        inspect.ismodule(value)
        or inspect.isclass(value)
        or inspect.isfunction(value)
        or inspect.ismethod(value)
        or inspect.isbuiltin(value)
    )


def _says_only_where_it_is_from(watched_value: assertions.WatchedValue) -> bool:
    """
    A bare name for a module, a class or a function: `User` in
    `isinstance(user, User)`. What it prints as is where it was defined,
    which the name already says. One side of a comparison is always
    printed, since there the value is what was compared.
    """
    return (
        not watched_value.is_operand
        and watched_value.source.isidentifier()
        and _is_module_class_or_function(watched_value.value)
    )


def _locals_of_the_test(
    error: BaseException,
    *,
    test: RunnableTest,
    printer: ValuePrinter,
    already_printed: set[str],
) -> tuple[LocalValue, ...]:
    step = _step_of_the_test(error, test=test)
    if step is None:
        return ()
    frame = step.tb_frame

    values = []
    for name, value in frame.f_locals.items():
        if name in already_printed or name.startswith(_KEPT_BY_AN_ASSERT):
            continue
        if _is_module_class_or_function(value):
            continue
        values.append(LocalValue(name=name, value=printer.printed(value, name=name)))
    return tuple(values)


def _step_of_the_test(
    error: BaseException, *, test: RunnableTest
) -> types.TracebackType | None:
    """
    The step of the traceback that is the test function. It is where the
    failure started from, however far below it the error was raised.
    """
    if test.function is None:
        return None
    # A decorator that wraps the test (`@mock.patch`) has a frame of its
    # own above it. The test's is the one running the test's own code.
    code = inspect.unwrap(test.function).__code__

    tb = error.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code is code:
            return tb
        tb = tb.tb_next
    return None
