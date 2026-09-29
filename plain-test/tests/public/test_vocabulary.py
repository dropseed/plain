import enum

from plain.test import TestDefinitionError, case, cases, raises, skip, tag
from plain.test.decorators import TEST_CASES_ATTRIBUTE


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


@cases(("a", True), ("", False))
def test_cases_pass_arguments(value, expected):
    assert bool(value) is expected


@cases(
    case("a@example.com", True, id="plain address"),
    case("nope", False, id="no at sign"),
)
def test_case_ids_pass_arguments(value, expected):
    assert ("@" in value) is expected


def test_case_requires_a_non_empty_id():
    with raises(TestDefinitionError, match="non-empty id"):
        case("x", id="")


def test_cases_rejects_duplicate_ids():
    with raises(TestDefinitionError, match="ids must be unique"):
        cases(case("a", id="same"), case("b", id="same"))


def case_ids(decorator):
    def test_x(*values):
        pass

    decorator(test_x)
    return [case_id for _, case_id in getattr(test_x, TEST_CASES_ATTRIBUTE)]


def test_a_case_is_named_for_its_values():
    assert case_ids(cases(("a@example.com", True), ("nope", False))) == [
        "a@example.com-True",
        "nope-False",
    ]
    assert case_ids(cases(5, 0.5, None)) == ["5", "0.5", "None"]


class Plan(enum.Enum):
    MONTHLY = 1
    ANNUAL = 2


def test_an_enum_member_is_named_by_its_name():
    assert case_ids(cases((Plan.MONTHLY, 10), (Plan.ANNUAL, 100))) == [
        "MONTHLY-10",
        "ANNUAL-100",
    ]


@cases(
    case([1], [2], id="a value that isn't a word or a number"),
    case("first\nsecond", "x", id="a string with a line break in it"),
    case(" padded", "x", id="a string with a space at one end"),
    case("", "x", id="an empty string"),
    case("same", "same", id="two cases that would be named the same"),
    case("x" * 61, "y", id="a name too long to read"),
)
def test_cases_are_numbered_when_one_cannot_be_named_for_its_values(first, second):
    # All of them, the one that could have been named too: one test's cases
    # are named or numbered, not some of each.
    assert case_ids(cases(first, second)) == ["0", "1"]


def test_a_name_given_to_a_case_wins():
    assert case_ids(cases(case(1, id="one"), 2)) == ["one", "2"]
    assert case_ids(cases(case([1], id="a list"), [2])) == ["a list", "1"]


def test_a_name_that_is_another_cases_number_is_refused():
    with raises(TestDefinitionError, match="ids must be unique") as caught:
        cases([1], case([2], id="0"))
    assert "case 1 is named '0', which is what case 0 is numbered" in str(
        caught.exception
    )


def test_a_name_that_is_what_another_case_would_be_called_is_refused():
    # Named for its values the last case is "2", and numbered it is 2.
    with raises(TestDefinitionError, match="ids must be unique"):
        cases(case(1, id="2"), 5, 2)


def test_case_repr_names_its_values_and_id():
    assert repr(case(1, 2, id="pair")) == "case(1, 2, id='pair')"


def test_a_second_cases_raises_instead_of_replacing_the_first():
    def test_pairs(letter, number):
        pass

    cases(1, 2)(test_pairs)
    with raises(TestDefinitionError, match="test_pairs already has @cases") as caught:
        cases("a", "b")(test_pairs)
    assert "itertools.product" in str(caught.exception)


def test_skip_requires_a_reason():
    with raises(TestDefinitionError, match="@skip requires a reason"):
        skip("")

    def test_never():
        pass

    # A bare `@skip` hands the function in where the reason goes.
    with raises(TestDefinitionError, match="@skip requires a reason"):
        skip(test_never)  # ty: ignore[invalid-argument-type]


def test_tag_requires_names():
    with raises(TestDefinitionError, match="@tag requires at least one name"):
        tag()

    def test_never():
        pass

    with raises(TestDefinitionError, match="@tag requires at least one name"):
        tag(test_never)  # ty: ignore[invalid-argument-type]
