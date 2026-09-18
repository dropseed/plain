import os

from plain.test import cases, patch, raises


def test_raises_catches_and_exposes_exception():
    with raises(ValueError) as caught:
        raise ValueError("bad thing")
    assert "bad thing" in str(caught.exception)


def test_raises_match():
    with raises(ValueError, match="bad"):
        raise ValueError("a bad thing")


def test_raises_match_failure():
    with raises(AssertionError), raises(ValueError, match="unrelated"):
        raise ValueError("a bad thing")


def test_raises_reports_missing_exception():
    with raises(AssertionError) as caught, raises(ValueError):
        pass
    assert "ValueError was not raised" in str(caught.exception)


def test_raises_lets_unexpected_exceptions_propagate():
    with raises(KeyError), raises(ValueError):
        raise KeyError("different")


def test_raises_exception_is_unreadable_inside_the_block():
    """Nothing has been caught yet, so say so rather than hand back a None
    that fails somewhere further down the test."""
    with (
        raises(AttributeError, match="only available after"),
        raises(ValueError) as caught,
    ):
        caught.exception  # noqa: B018 — the attribute access is the assertion


def test_raises_exception_keeps_the_caught_subclass():
    class Specific(ValueError):
        detail = "specific"

    with raises(ValueError) as caught:
        raise Specific("boom")

    assert caught.exception.detail == "specific"  # ty: ignore[unresolved-attribute]


class Thing:
    attr = "original"


def test_patch_attribute_restores():
    with patch(Thing, "attr", "changed"):
        assert Thing.attr == "changed"
    assert Thing.attr == "original"


def test_patch_mapping_restores_and_removes():
    with patch(os.environ, "PLAIN_TESTING_PATCH_TEST", "on"):
        assert os.environ["PLAIN_TESTING_PATCH_TEST"] == "on"
    assert "PLAIN_TESTING_PATCH_TEST" not in os.environ


@cases(("a", True), ("", False))
def test_cases_pass_arguments(value, expected):
    assert bool(value) is expected
