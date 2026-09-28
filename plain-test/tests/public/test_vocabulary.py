import os

from plain.test import TestDefinitionError, case, cases, patch, raises, skip, tag


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


class InheritingThing(Thing):
    pass


def test_patch_inherited_attribute_leaves_nothing_on_the_subclass():
    with patch(InheritingThing, "attr", "changed"):
        assert InheritingThing.attr == "changed"
        assert Thing.attr == "original"
    assert "attr" not in vars(InheritingThing)
    assert InheritingThing.attr == "original"


class ThingWithMethods:
    @staticmethod
    def double(value):
        return value * 2

    @classmethod
    def name(cls):
        return cls.__name__


def test_patch_staticmethod_restores_a_staticmethod():
    with patch(ThingWithMethods, "double", lambda value: value * 3):
        assert ThingWithMethods.double(2) == 6
    # Called through an instance: a plain function here would receive `self`.
    assert ThingWithMethods().double(2) == 4


def test_patch_classmethod_restores_a_classmethod():
    with patch(ThingWithMethods, "name", lambda: "patched"):
        assert ThingWithMethods.name() == "patched"

    class Child(ThingWithMethods):
        pass

    # A bound method put back in place would still answer for the parent.
    assert Child.name() == "Child"


def test_patch_rejects_a_name_the_target_does_not_have():
    with raises(AttributeError), patch(Thing, "no_such_attribute", "value"):
        pass


def test_patch_mapping_restores_and_removes():
    with patch(os.environ, "PLAIN_TESTING_PATCH_TEST", "on"):
        assert os.environ["PLAIN_TESTING_PATCH_TEST"] == "on"
    assert "PLAIN_TESTING_PATCH_TEST" not in os.environ


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
