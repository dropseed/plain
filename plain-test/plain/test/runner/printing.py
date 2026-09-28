"""
Printing a value in a failure report.

Three things a report's reader is owed. A value is printed whole, or the
report says how much was left out and how to see it. Two large values that
were expected to be equal are printed as what differs between them. And
printing never goes wrong: a `repr` that raises is reported as having
raised, and doesn't take the report with it.

A value is printed by `pprint`, which puts a container that doesn't fit on
a line one item to a line. A package can print the values it owns better
than their `repr` does, through its lifecycle's `describe_value()`.
"""

import difflib
import pprint
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = []

# The most of one value a report prints, in characters.
VALUE_CAP = 2_000
# The most of one diff a report prints, in lines.
DIFF_LINE_CAP = 60
# The flag that lifts both.
FULL_VALUES_FLAG = "--full-values"

# A value that prints on one line no longer than this is small: it is
# printed whole, and two of them are not diffed.
_ONE_LINE = 80

# How much of two long one-line strings is shown on each side of the first
# place they differ.
_BEFORE_THE_DIFFERENCE = 30
_AFTER_THE_DIFFERENCE = 50

type Describer = Callable[[object], str | None]


@dataclass(frozen=True, kw_only=True)
class PrintedValue:
    """A value as a report prints it."""

    # One line or several.
    text: str
    # How many characters the cap left out. 0 when `text` is the whole value.
    cut_characters: int = 0


@dataclass(frozen=True, kw_only=True)
class Diff:
    """What differs between two values that were expected to be equal."""

    # A unified diff: `-` is the left side's, `+` is the right side's.
    lines: tuple[str, ...]
    # How many lines the cap left out. 0 when `lines` is the whole diff.
    cut_lines: int = 0


class _GuardedPrinter(pprint.PrettyPrinter):
    """A PrettyPrinter that a `repr` can't stop by raising."""

    def format(
        self, object: object, context: dict, maxlevels: int, level: int
    ) -> tuple[str, bool, bool]:
        try:
            return super().format(object, context, maxlevels, level)
        except Exception as error:
            return what_repr_raised(object, error), False, False


def what_repr_raised(value: object, error: Exception) -> str:
    return (
        f"<{type(value).__qualname__}: its repr raised "
        f"{type(error).__qualname__}: {error}>"
    )


class ValuePrinter:
    def __init__(
        self, *, describers: Sequence[Describer] = (), full_values: bool = False
    ) -> None:
        self.describers = describers
        self.full_values = full_values

    def printed(self, value: object) -> PrintedValue:
        """The value, whole or cut at the cap."""
        text = self._whole(value)
        if self.full_values or len(text) <= VALUE_CAP:
            return PrintedValue(text=text)
        return PrintedValue(text=text[:VALUE_CAP], cut_characters=len(text) - VALUE_CAP)

    def summarized(self, value: object) -> PrintedValue:
        """What kind of value it is and how big, for one the diff shows."""
        return PrintedValue(text=_summary(value))

    def diff(
        self, left: object, right: object, *, left_source: str, right_source: str
    ) -> Diff | None:
        """
        What differs between two values, or None when both are small enough
        to read side by side.
        """
        left_text = self._whole(left, sort_dicts=True)
        right_text = self._whole(right, sort_dicts=True)

        if isinstance(left, str) and isinstance(right, str):
            # Text of more than one line is compared line by line however
            # short it is. Its `repr` is one line with `\n` in it, which
            # is small and is no way to read it.
            has_lines = "\n" in left or "\n" in right
            if not has_lines and _is_small(left_text) and _is_small(right_text):
                return None
            lines = _text_diff(
                left, right, left_source=left_source, right_source=right_source
            )
        elif _is_small(left_text) and _is_small(right_text):
            return None
        else:
            lines = _line_diff(
                left_text.splitlines(),
                right_text.splitlines(),
                left_source=left_source,
                right_source=right_source,
            )

        if self.full_values or len(lines) <= DIFF_LINE_CAP:
            return Diff(lines=tuple(lines))
        return Diff(
            lines=tuple(lines[:DIFF_LINE_CAP]),
            cut_lines=len(lines) - DIFF_LINE_CAP,
        )

    def _whole(self, value: object, *, sort_dicts: bool = False) -> str:
        described = self._described(value)
        if described is not None:
            return described
        printer = _GuardedPrinter(width=_ONE_LINE, sort_dicts=sort_dicts)
        try:
            return printer.pformat(value)
        except Exception as error:
            # Not a repr this time: a `__len__` or an `__iter__` that raised
            # while the printer was laying the value out.
            return what_repr_raised(value, error)

    def _described(self, value: object) -> str | None:
        for describe in self.describers:
            try:
                described = describe(value)
            except Exception:
                # A describer that fails is a describer with nothing to say.
                continue
            if described is not None:
                return str(described)
        return None


def _is_small(text: str) -> bool:
    return "\n" not in text and len(text) <= _ONE_LINE


def _summary(value: Any) -> str:
    name = type(value).__qualname__
    if isinstance(value, str):
        characters = _counted(len(value), "character")
        lines = _counted(len(value.splitlines()), "line")
        return f"<{name}, {characters} in {lines}>"
    if isinstance(value, bytes):
        return f"<{name}, {_counted(len(value), 'byte')}>"
    if isinstance(value, dict):
        return f"<{name} with {_counted(len(value), 'key')}>"
    if isinstance(value, list | tuple | set | frozenset):
        return f"<{name} with {_counted(len(value), 'item')}>"
    return f"<{name}>"


def _counted(count: int, what: str) -> str:
    return f"{count:,} {what}" if count == 1 else f"{count:,} {what}s"


def _line_diff(
    left_lines: list[str],
    right_lines: list[str],
    *,
    left_source: str,
    right_source: str,
) -> list[str]:
    return list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=left_source,
            tofile=right_source,
            n=2,
            lineterm="",
        )
    )


def _text_diff(
    left: str, right: str, *, left_source: str, right_source: str
) -> list[str]:
    """
    Two strings, line by line as they read. Where reading them wouldn't show
    everything (a space at the end of a line, a line ending that is there on
    one side only), each line's `repr`, which does.
    """
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    if len(left_lines) <= 1 and len(right_lines) <= 1:
        return _one_line_text_diff(left, right)

    end_the_same_way = left.endswith("\n") == right.endswith("\n")
    if _reads_as_it_is(left) and _reads_as_it_is(right) and end_the_same_way:
        return _line_diff(
            left_lines,
            right_lines,
            left_source=left_source,
            right_source=right_source,
        )
    return _line_diff(
        [repr(line) for line in left.splitlines(keepends=True)],
        [repr(line) for line in right.splitlines(keepends=True)],
        left_source=left_source,
        right_source=right_source,
    )


def _reads_as_it_is(text: str) -> bool:
    """Whether every character of a text's lines can be seen when printed."""
    return all(
        line == line.rstrip() and line.isprintable() for line in text.split("\n")
    )


def _one_line_text_diff(left: str, right: str) -> list[str]:
    """
    Two strings with no lines to go by: where they first differ, and what
    is around that on each side.
    """
    at = 0
    while at < min(len(left), len(right)) and left[at] == right[at]:
        at += 1
    start = max(0, at - _BEFORE_THE_DIFFERENCE)
    stop = at + _AFTER_THE_DIFFERENCE

    def around(text: str) -> str:
        before = "..." if start > 0 else ""
        after = "..." if stop < len(text) else ""
        return f"{before}{text[start:stop]!r}{after}"

    where = (
        f"first difference at character {at:,}"
        f" (left is {len(left):,} characters, right is {len(right):,})"
    )
    return [
        where,
        f"- {around(left)}",
        f"+ {around(right)}",
    ]
