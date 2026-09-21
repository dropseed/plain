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

from typing import Any, ClassVar

from plain.postgres import Field, ModelMixin, types
from plain.postgres import Field as AliasedField
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


class OrdinaryMixin:
    """A plain Python mixin -- no `postgres.ModelMixin`, so PEP 681 leaves its
    fields out of the synthesized constructor. It still *types the attribute*,
    which is all this check cares about."""

    # No dataclass transform here, so ty runs the ordinary assignment check and
    # catches the spelling. On a model it stays silent -- which is the gap this
    # preflight check covers.
    owner: AnnotationTarget = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


class UsesOrdinaryMixin(OrdinaryMixin, Model):
    model_options = postgres.Options(package_label="examples")


class AliasAnnotated(Model):
    """`Field` under an import alias is the same class, so it reads the same."""

    model_options = postgres.Options(package_label="examples")

    owner: AliasedField[AnnotationTarget] = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


class ClassVarAnnotated(Model):
    """`ClassVar[...]` is the declared way to keep an attribute out of the
    constructor, so it isn't this check's business -- and `Field[ClassVar[...]]`
    would be a nonsense repair to suggest."""

    model_options = postgres.Options(package_label="examples")

    owner: ClassVar[Field[AnnotationTarget]] = types.ForeignKeyField(
        "examples.AnnotationTarget", on_delete=postgres.CASCADE
    )


# A module compiled without `from __future__ import annotations`, so its
# annotations arrive as evaluated objects rather than strings. `str()` renders
# one as `<class 'tests...AnnotationTarget'>`, which has no business in a fix
# message telling someone what to type.
_EVALUATED: dict[str, Any] = {
    "__name__": __name__,
    "Model": Model,
    "types": types,
    "postgres": postgres,
    "AnnotationTarget": AnnotationTarget,
}
_EVALUATED_SOURCE = (
    "class EvaluatedAnnotations(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    owner: AnnotationTarget = types.ForeignKeyField(\n"
    "        'examples.AnnotationTarget', on_delete=postgres.CASCADE\n"
    "    )\n"
    "    backup: AnnotationTarget | None = types.ForeignKeyField(\n"
    "        'examples.AnnotationTarget', on_delete=postgres.SET_NULL,\n"
    "        allow_null=True, required=False, default=None,\n"
    "    )\n"
)
# `dont_inherit` matters: without it the compiler hands this module's
# `from __future__ import annotations` down to the nested compile and the
# annotations come back as strings -- the case already covered above.
exec(  # noqa: S102
    compile(_EVALUATED_SOURCE, "<evaluated annotations>", "exec", dont_inherit=True),
    _EVALUATED,
)
EvaluatedAnnotations: type = _EVALUATED["EvaluatedAnnotations"]


def test_an_ordinary_mixins_annotation_is_read_too():
    """The transform gates the *constructor* checks, where PEP 681 really does
    ignore a transformless base. It has nothing to say about attribute types:
    a plain mixin types `UsesOrdinaryMixin.owner` exactly as a model would."""
    assert foreign_keys_annotated_as_values(UsesOrdinaryMixin) == [
        ("owner", "AnnotationTarget")
    ]


def test_an_import_alias_for_field_is_recognized():
    """Recognition resolves the annotation's head against the declaring
    module, so it follows aliases instead of matching on the spelling."""
    assert foreign_keys_annotated_as_values(AliasAnnotated) == []


def test_a_classvar_annotation_is_left_alone():
    assert foreign_keys_annotated_as_values(ClassVarAnnotated) == []


def test_an_evaluated_class_annotation_yields_a_valid_rewrite():
    """Nothing in the message may be un-typeable: the annotation is named by
    qualname, and `| None` comes from the field's allow_null rather than from
    the annotation text."""
    assert EvaluatedAnnotations.__annotations__["owner"] is AnnotationTarget

    fixes = {
        str(r.obj).rsplit(".", 1)[-1]: r.fix
        for r in foreign_key_annotation_results(EvaluatedAnnotations)
    }
    required = fixes["owner"]
    nullable = fixes["backup"]

    assert "<class" not in required
    assert "<class" not in nullable
    assert "'owner: Field[AnnotationTarget] = ...'" in required
    assert "default=None" not in required
    assert (
        "'backup: Field[AnnotationTarget | None] = ...' with default=None" in nullable
    )


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
