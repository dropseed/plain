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

A fourth thing is owed to whoever the report is shown to: it doesn't print
what is known to be secret. The environment is printed as its names, with
no values. A package leaves the secrets it owns out of what it describes.
That is done for a value wherever it is: on its own, or inside a list, a
tuple, a dict or a set, however far in. A secret that is a string like any
other by the time the test has it can't be told from one, and is printed.
"""

import difflib
import os
import pprint
from collections.abc import Callable, ItemsView, Sequence, ValuesView
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
    # Set when the report has printed this value already, under this name.
    # `text` says so, and the value isn't printed again.
    same_as: str | None = None


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


class _AlreadyText:
    """Text printed as it is, where a value's `repr` would have been."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def _is_the_environments(key: object, item: object) -> bool:
    return (
        isinstance(key, str) and isinstance(item, str) and os.environ.get(key) == item
    )


def _names_only(environment: os._Environ) -> str:
    names = ", ".join(sorted(str(name) for name in environment))
    return f"environ({_counted(len(environment), 'name')}, values withheld: {names})"


class ValuePrinter:
    """
    Prints the values of one failure. It remembers what it has printed, so
    that a large value the failure has in it twice is printed once.
    """

    def __init__(
        self, *, describers: Sequence[Describer] = (), full_values: bool = False
    ) -> None:
        self.describers = describers
        self.full_values = full_values
        # The text of each large value printed so far, and the name it was
        # printed under.
        self._printed_as: dict[str, str] = {}

    def printed(self, value: object, *, name: str | None = None) -> PrintedValue:
        """
        The value, whole or cut at the cap. `name` is what the report calls
        it: a value printed under a name is not printed again under
        another, and the second is said to be the same as the first.
        """
        text = self._whole(value)

        if name is not None and not _is_small(text):
            first_name = self._printed_as.setdefault(text, name)
            if first_name != name:
                return PrintedValue(
                    text=f"<the same as {first_name}>", same_as=first_name
                )

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
        try:
            fit_to_print = self._fit_to_print(value, inside=frozenset())
        except RecursionError:
            return f"<{type(value).__qualname__}: nested too deeply to print>"
        if isinstance(fit_to_print, _AlreadyText):
            return fit_to_print.text

        printer = _GuardedPrinter(width=_ONE_LINE, sort_dicts=sort_dicts)
        try:
            return printer.pformat(fit_to_print)
        except Exception as error:
            # Not a repr this time: a `__len__` or an `__iter__` that raised
            # while the printer was laying the value out.
            return what_repr_raised(value, error)

    def _fit_to_print(self, value: object, *, inside: frozenset[int]) -> object:
        """
        The value as it can be handed to `pprint`: itself, or the text a
        package describes it by, or a copy of a container with the same
        done to everything in it.
        """
        described = self._described(value)
        if described is not None:
            return _AlreadyText(described)

        if isinstance(value, os._Environ):
            return _AlreadyText(_names_only(value))
        is_a_view = isinstance(value, ValuesView | ItemsView)
        if is_a_view and getattr(value, "_mapping", None) is os.environ:
            kind = type(value).__qualname__
            return _AlreadyText(f"<{kind} of the environment, withheld>")

        if id(value) in inside:
            # One that is inside itself is left for `pprint`, which says so.
            return value
        inside = inside | {id(value)}

        # A subclass of one of these prints as its own `repr` says, which
        # isn't the printer's to take apart.
        if isinstance(value, dict):
            if type(value) is not dict:
                return value
            return self._dict_fit_to_print(value, inside=inside)
        if isinstance(value, list | tuple | set | frozenset):
            if type(value) not in (list, tuple, set, frozenset):
                return value
            return type(value)(
                self._fit_to_print(item, inside=inside) for item in value
            )
        return value

    def _dict_fit_to_print(self, value: dict, *, inside: frozenset[int]) -> dict:
        """
        A dict made from the environment, all of it or some of it, as
        `{**os.environ, "DEBUG": "1"}` is for a subprocess, is printed
        without what it took: that is the environment's still. What was
        taken is said once, by name, after the items that are the dict's
        own.
        """
        fit_to_print: dict[object, object] = {}
        from_the_environment = []
        for key, item in value.items():
            if _is_the_environments(key, item):
                from_the_environment.append(key)
            else:
                fit_to_print[key] = self._fit_to_print(item, inside=inside)

        if from_the_environment:
            names = ", ".join(sorted(from_the_environment))
            taken = _counted(len(from_the_environment), "name")
            fit_to_print[_AlreadyText(f"<{taken} from the environment>")] = (
                _AlreadyText(f"<values withheld: {names}>")
            )
        return fit_to_print

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
