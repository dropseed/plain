"""
Declarative test decorators.

Decorators declare static facts about a test — they never inject runtime
values or alter control flow. The test runner (plain.testing.runner) reads the
attributes they attach.
"""

import enum
from collections.abc import Callable
from typing import Any

from .definition import TestDefinitionError

__all__ = ["case", "cases", "skip", "tag"]

# Attribute names the runner reads. Unique and greppable on purpose.
TEST_CASES_ATTRIBUTE = "__plain_test_cases__"
TEST_SKIP_ATTRIBUTE = "__plain_test_skip__"
TEST_TAGS_ATTRIBUTE = "__plain_test_tags__"


class case:
    """
    One `@cases` entry with a name of its own.

        @cases(
            case("a@example.com", True, id="plain address"),
            case("nope", False, id="no at sign"),
        )
        def test_email_validation(email, valid):
            assert is_valid_email(email) is valid

    The id becomes the test id — `test_email_validation[no at sign]` — so a
    failure and its re-run command name the case for what it is about. The
    id sits on the case it names, so adding or reordering cases can't
    quietly shift the names onto the wrong values.
    """

    __slots__ = ("id", "values")

    def __init__(self, *values: Any, id: str) -> None:
        if not id or not id.strip():
            raise TestDefinitionError("case() requires a non-empty id")
        self.values = values
        self.id = id

    def __repr__(self) -> str:
        arguments = ", ".join(repr(value) for value in self.values)
        return f"case({arguments}, id={self.id!r})"


# A case's id is put between brackets after the test's name, and typed after
# `plain test`. Past this many characters it says less than a number would.
_LONGEST_ID_FROM_VALUES = 60


def cases(*case_args: Any) -> Callable:
    """
    Run a test once for each case. Each argument is a case, passed as the
    test function's positional arguments.

        @cases(
            ("a@example.com", True),
            ("nope", False),
        )
        def test_email_validation(email, valid):
            assert is_valid_email(email) is valid

    A non-tuple case is passed as a single argument.

    A case is reported by its values, joined with `-`:
    `test_email_validation[nope-False]`. That needs every value of every
    case to be a string, a number, a boolean, `None` or an enum member, and
    every case to come out different. Otherwise the cases are numbered,
    `test_email_validation[0]`. Wrap a case in `case(..., id="...")` to give
    it a name of its own.

    A test takes one `@cases`, and each case is one flat tuple: the test's
    values in the order of its parameters. For every combination of two
    lists, build the cases from both:

        @cases(*[(a, b, c) for a in FIRST for b, c in SECOND])

    Each `for` names what one entry of its list holds.
    """
    entries: list[tuple[tuple[Any, ...], str | None]] = []
    for entry in case_args:
        if isinstance(entry, case):
            entries.append((entry.values, entry.id))
        elif isinstance(entry, tuple):
            entries.append((entry, None))
        else:
            entries.append(((entry,), None))

    if not entries:
        raise TestDefinitionError("cases() requires at least one case")

    given_ids = [given_id for _, given_id in entries if given_id is not None]
    duplicates = {given_id for given_id in given_ids if given_ids.count(given_id) > 1}
    if duplicates:
        raise TestDefinitionError(
            f"cases() ids must be unique — repeated: {sorted(duplicates)}"
        )

    ids = _ids_from_values(entries)
    if ids is None:
        ids = _ids_from_positions(entries)
    normalized = [(values, id) for (values, _), id in zip(entries, ids, strict=True)]

    def decorator(func: Callable) -> Callable:
        if TEST_CASES_ATTRIBUTE in vars(func):
            name = getattr(func, "__name__", "this test")
            raise TestDefinitionError(
                f"{name} already has @cases. A second one would "
                "replace the first, not combine with it. Write the "
                "combinations as one @cases. Each case is one flat tuple: "
                "the test's values, in the order of its parameters.\n"
                "\n"
                "    @cases(*[(a, b, c) for a in FIRST for b, c in SECOND])\n"
                f"    def {name}(a, b, c): ...\n"
                "\n"
                "Each `for` names what one entry of its list holds: "
                "`for a in FIRST` when the entries are single values, "
                "`for b, c in SECOND` when they are tuples. "
                "(`itertools.product` would nest those: `(a, (b, c))`.)"
            )
        setattr(func, TEST_CASES_ATTRIBUTE, normalized)
        return func

    return decorator


def _ids_from_values(
    entries: list[tuple[tuple[Any, ...], str | None]],
) -> list[str] | None:
    """
    An id for every case: the one it was given, or its values joined with
    `-`. None when a case's values can't be written that way, or when two
    cases would come out the same. Then none of them are named for their
    values, so that one test's cases are all named or all numbered.
    """
    ids = []
    for values, given_id in entries:
        if given_id is not None:
            ids.append(given_id)
            continue
        written = [_written_in_an_id(value) for value in values]
        if not written or None in written:
            return None
        from_values = "-".join(part for part in written if part is not None)
        if len(from_values) > _LONGEST_ID_FROM_VALUES:
            return None
        ids.append(from_values)

    if len(set(ids)) != len(ids):
        return None
    return ids


def _written_in_an_id(value: Any) -> str | None:
    """A value as it is written in a case's id, or None if it can't be."""
    if isinstance(value, enum.Enum):
        return value.name
    if value is None or type(value) in (bool, int, float):
        return repr(value)
    # A string has to be readable where it is printed, and the same when it
    # is typed back: nothing that isn't a character to look at, and no space
    # at either end to be lost.
    if type(value) is str and value and value.isprintable() and value == value.strip():
        return value
    return None


def _ids_from_positions(
    entries: list[tuple[tuple[Any, ...], str | None]],
) -> list[str]:
    """An id for every case: the one it was given, or its number."""
    ids = []
    for position, (_, given_id) in enumerate(entries):
        ids.append(given_id if given_id is not None else str(position))

    for position, (_, given_id) in enumerate(entries):
        if given_id is None:
            continue
        if ids.count(given_id) > 1:
            numbered = ids.index(given_id)
            if numbered == position:
                numbered = ids.index(given_id, position + 1)
            raise TestDefinitionError(
                f"cases() ids must be unique — case {position} is named "
                f"{given_id!r}, which is what case {numbered} is numbered. "
                "Give it another name."
            )
    return ids


def skip(reason: str) -> Callable:
    """
    Always skip this test, with the reason shown in the report.

    To skip from inside a running test, call `skip_test(reason)`.
    """
    # A bare `@skip` would hand the test function in as the reason, and the
    # test would silently stop existing.
    if not isinstance(reason, str) or not reason.strip():
        raise TestDefinitionError('@skip requires a reason: @skip("why")')

    def decorator(func: Callable) -> Callable:
        setattr(func, TEST_SKIP_ATTRIBUTE, reason)
        return func

    return decorator


def tag(*names: str) -> Callable:
    """
    Label a test for selection (`plain test --tag slow`) or for package
    lifecycles that change behavior per-test (e.g. `@isolated_db` from
    plain.postgres is a tag under the hood).
    """

    # A bare `@tag` would hand the test function in as a name, and the test
    # would silently stop existing.
    if not names or not all(isinstance(name, str) and name.strip() for name in names):
        raise TestDefinitionError('@tag requires at least one name: @tag("slow")')

    def decorator(func: Callable) -> Callable:
        existing = getattr(func, TEST_TAGS_ATTRIBUTE, ())
        setattr(func, TEST_TAGS_ATTRIBUTE, (*existing, *names))
        return func

    return decorator
