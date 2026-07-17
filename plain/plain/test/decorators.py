"""
Declarative test decorators.

Decorators declare static facts about a test — they never inject runtime
values or alter control flow. The test runner (plain.testing) reads the
attributes they attach.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["cases", "skip", "tag"]

# Attribute names the runner reads. Unique and greppable on purpose.
TEST_CASES_ATTRIBUTE = "__plain_test_cases__"
TEST_SKIP_ATTRIBUTE = "__plain_test_skip__"
TEST_TAGS_ATTRIBUTE = "__plain_test_tags__"


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

    A non-tuple case is passed as a single argument.
    """
    normalized = [case if isinstance(case, tuple) else (case,) for case in case_args]
    if not normalized:
        raise TypeError("cases() requires at least one case")

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
