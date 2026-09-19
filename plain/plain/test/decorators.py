"""
Declarative test decorators.

Decorators declare static facts about a test — they never inject runtime
values or alter control flow. The test runner (plain.testing) reads the
attributes they attach.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
    failure and its re-run command name the case instead of numbering it.
    The id sits on the case it names, so adding or reordering cases can't
    quietly shift the names onto the wrong values.
    """

    __slots__ = ("id", "values")

    def __init__(self, *values: Any, id: str) -> None:
        if not id or not id.strip():
            raise TypeError("case() requires a non-empty id")
        self.values = values
        self.id = id

    def __repr__(self) -> str:
        arguments = ", ".join(repr(value) for value in self.values)
        return f"case({arguments}, id={self.id!r})"


def cases(*case_args: Any) -> Callable:
    """
    Parametrize a test. Each argument becomes its own test run, passed as
    the test function's positional arguments.

        @cases(
            ("a@example.com", True),
            ("nope", False),
        )
        def test_email_validation(email, valid):
            assert is_valid_email(email) is valid

    A non-tuple case is passed as a single argument. Cases are reported by
    position (`test_email_validation[0]`); wrap one in `case(..., id="...")`
    to name it instead.
    """
    normalized: list[tuple[tuple[Any, ...], str | None]] = []
    for entry in case_args:
        if isinstance(entry, case):
            normalized.append((entry.values, entry.id))
        elif isinstance(entry, tuple):
            normalized.append((entry, None))
        else:
            normalized.append(((entry,), None))

    if not normalized:
        raise TypeError("cases() requires at least one case")

    explicit_ids = [case_id for _, case_id in normalized if case_id is not None]
    duplicates = {
        case_id for case_id in explicit_ids if explicit_ids.count(case_id) > 1
    }
    if duplicates:
        raise TypeError(f"cases() ids must be unique — repeated: {sorted(duplicates)}")

    def decorator(func: Callable) -> Callable:
        setattr(func, TEST_CASES_ATTRIBUTE, normalized)
        return func

    return decorator


def skip(reason: str) -> Callable:
    """Always skip this test, with the reason shown in the report."""

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

    def decorator(func: Callable) -> Callable:
        existing = getattr(func, TEST_TAGS_ATTRIBUTE, ())
        setattr(func, TEST_TAGS_ATTRIBUTE, (*existing, *names))
        return func

    return decorator
