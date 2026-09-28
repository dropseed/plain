"""
What a failed test carries away from its failure.

A `Failure` is everything the report says about one failed test, already
printed: text, and nothing that is still alive. It is made while the test's
lifecycles are still in place and the values are as the test left them,
and then the error, its frames and everything they held are let go.

The reporter turns a `Failure` into what is printed. Anything else that
reports a run reads the same structure.
"""

import inspect
import shlex
import traceback
import types
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import assertions
from .collection import RunnableTest
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
class Failure:
    # "AssertionError", "KeyError"
    error_type: str
    error_message: str
    # Formatted, with the runner's own frames taken off the top.
    traceback: str
    # None when what failed wasn't an assert in a test file.
    failed_assert: FailedAssert | None
    # The test function's, in the order they were bound, without the ones
    # `failed_assert` has already printed.
    locals: tuple[LocalValue, ...]
    # The command that runs this test again, safe to paste.
    rerun_command: str


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

    return Failure(
        error_type=type(error).__qualname__,
        error_message=_guarded_str(error),
        traceback=format_traceback(error),
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
    return Failure(
        error_type=type(error).__qualname__,
        error_message=_guarded_str(error),
        traceback=format_traceback(error)
        + "\n(The values couldn't be printed: "
        + f"{type(while_describing).__qualname__}: {while_describing})\n",
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


def format_traceback(error: BaseException) -> str:
    """Format a traceback with the runner's own frames trimmed off the top."""
    tb = error.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if not filename.startswith(_RUNNER_DIRECTORY) and "contextlib" not in filename:
            break
        tb = tb.tb_next

    return "".join(
        traceback.format_exception(type(error), error, tb or error.__traceback__)
    )


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
            value = printer.printed(watched_value.value)

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
    frame = _frame_of_the_test(error, test=test)
    if frame is None:
        return ()

    values = []
    for name, value in frame.f_locals.items():
        if name in already_printed or name.startswith(_KEPT_BY_AN_ASSERT):
            continue
        if _is_module_class_or_function(value):
            continue
        values.append(LocalValue(name=name, value=printer.printed(value)))
    return tuple(values)


def _frame_of_the_test(
    error: BaseException, *, test: RunnableTest
) -> types.FrameType | None:
    """
    The frame the test function ran in. It is where the failure started
    from, however far below it the error was raised.
    """
    if test.function is None:
        return None
    # A decorator that wraps the test (`@mock.patch`) has a frame of its
    # own above it. The test's is the one running the test's own code.
    code = inspect.unwrap(test.function).__code__

    tb = error.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code is code:
            return tb.tb_frame
        tb = tb.tb_next
    return None
