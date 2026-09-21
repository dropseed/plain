"""The `postgres.foreign_key_annotated_as_value` check.

`ForeignKeyField` returns a descriptor that is a `Field[V]`, and `Field.__get__`
is what makes class access `type[Related]` (traversal) and instance access
`Related`. Annotating the attribute `Related` instead of `Field[Related]`
records a model instance, so the checker sees no field: `Model.user` is a
`User`, `Model.user.id` is an `int`, and the `where()` condition methods are
gone. That was the required spelling for a string model reference until the
string overloads started returning the descriptor; the check finds what's left.

The models here are deliberately unregistered -- they exist to be inspected,
not to hit a database -- so they're fed to `foreign_keys_annotated_as_values`
directly, while the registered-model sweep goes through the check itself.
"""

from __future__ import annotations

from plain.postgres import Field, ModelMixin, types
from plain.postgres.base import Model
from plain.postgres.preflight.models import (
    CheckForeignKeyAnnotatedAsValue,
    foreign_key_annotation_results,
    foreign_keys_annotated_as_values,
)

from plain import postgres


class AnnotationTarget(Model):
    model_options = postgres.Options(package_label="examples")

    name: Field[str] = types.TextField(max_length=10)


class ValueAnnotated(Model):
    model_options = postgres.Options(package_label="examples")

    # The old string-reference spelling, and its nullable sibling. The
    # non-nullable one still type-checks -- PEP 681 only compares a field
    # specifier's result against the annotation when the declaration passes
    # `default=` -- which is exactly why this check exists. The nullable one
    # does pass `default=`, so ty rejects it outright.
    owner: AnnotationTarget = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )
    backup: AnnotationTarget | None = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        "examples.AnnotationTarget",
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
    )


class FieldAnnotated(Model):
    model_options = postgres.Options(package_label="examples")

    owner: Field[AnnotationTarget] = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )
    backup: Field[AnnotationTarget | None] = types.ForeignKeyField(
        AnnotationTarget,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
    )


class Unannotated(Model):
    model_options = postgres.Options(package_label="examples")

    owner = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


def test_no_registered_model_annotates_a_foreign_key_as_a_value():
    """Every model in the test app's registry -- the example fixtures plus the
    first-party package models they pull in -- annotates its foreign keys
    `Field[...]`, so the check is silent."""
    results = CheckForeignKeyAnnotatedAsValue().run()
    assert not results, "Foreign keys annotated as values:\n" + "\n".join(
        r.fix for r in results
    )


class ValueAnnotatedMixin(ModelMixin):
    owner: AnnotationTarget = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


class ReannotatesTheMixinField(ValueAnnotatedMixin, Model):
    model_options = postgres.Options(package_label="examples")

    owner: Field[AnnotationTarget] = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


def test_reports_every_foreign_key_annotated_with_the_related_model():
    assert sorted(foreign_keys_annotated_as_values(ValueAnnotated)) == [
        ("backup", "AnnotationTarget | None"),
        ("owner", "AnnotationTarget"),
    ]


def test_a_field_annotation_clears_the_foreign_key():
    assert foreign_keys_annotated_as_values(FieldAnnotated) == []


def test_an_unannotated_foreign_key_is_not_this_checks_story():
    """An unannotated field isn't a constructor argument at all -- that's
    `postgres.field_leaks_into_constructor`'s counterpart in
    CheckTypedConstruction, not a wrong annotation."""
    assert foreign_keys_annotated_as_values(Unannotated) == []


def test_the_nearest_annotation_in_the_mro_is_the_one_read():
    """The checker reads the subclass's annotation, so a subclass that fixes a
    mixin's spelling clears the field rather than reporting it twice."""
    assert foreign_keys_annotated_as_values(ReannotatesTheMixinField) == []


def test_non_relation_fields_are_never_reported():
    assert foreign_keys_annotated_as_values(AnnotationTarget) == []


def test_results_are_warnings_that_name_the_field_and_the_rewrite():
    """Nothing is broken at runtime, so the check warns rather than fails."""
    results = foreign_key_annotation_results(ValueAnnotated)
    assert [r.id for r in results] == ["postgres.foreign_key_annotated_as_value"] * len(
        results
    )
    assert all(r.warning for r in results)
    fixes = " ".join(r.fix for r in results)
    assert "ValueAnnotated.owner" in fixes
    assert "Field[AnnotationTarget]" in fixes
    assert "Field[AnnotationTarget | None]" in fixes
    assert "TYPE_CHECKING" in fixes
