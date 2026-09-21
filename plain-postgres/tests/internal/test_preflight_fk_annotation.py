"""The `postgres.foreign_key_annotated_as_value` check.

`ForeignKeyField` returns a descriptor that is a `Field[V]`, and `Field.__get__`
is what makes class access `type[Related]` (traversal) and instance access
`Related`. Annotating the attribute `Related` instead of `Field[Related]`
records a model instance, so the checker sees no field: `Model.user` is a
`User`, `Model.user.id` is an `int`, and the `where()` condition methods are
gone. That was the required spelling for a string model reference until the
string overloads started returning the descriptor; the check finds what's left.

The check classifies an annotation rather than parsing it for meaning, and only
positive evidence that it names the related model warrants a warning. Evidence
that it names a `Field` clears it; anything else -- a name that doesn't resolve,
an unfamiliar wrapper, a spelling nobody anticipated -- says nothing. Most of
what follows is that second list: the shapes it must stay quiet about.

The models here are deliberately unregistered -- they exist to be inspected,
not to hit a database -- so they're fed to `foreign_keys_annotated_as_values`
directly, while the registered-model sweep goes through the check itself. They
name their foreign key's target by class rather than by string, because the
check reads the *annotation*; how the field names its target is irrelevant to
it, and a class argument resolves without a registry.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import TYPE_CHECKING, Annotated, Any, ClassVar

from plain.postgres import Field, ModelMixin, types
from plain.postgres import Field as AliasedField
from plain.postgres.base import Model
from plain.postgres.preflight.models import (
    CheckForeignKeyAnnotatedAsValue,
    foreign_key_annotation_results,
    foreign_keys_annotated_as_values,
)

from plain import postgres

if TYPE_CHECKING:
    # The common app spelling: postponed annotations plus a typing-only import.
    # At runtime this name simply isn't in the module.
    from plain.postgres import Field as TypeOnlyField

type FieldAlias = Field[Model]


def _class_in_module(
    module_name: str, class_name: str, source: str, *, postponed: bool, **names: Any
) -> type:
    """Build a class in a module of its own.

    What an annotation can and cannot resolve depends on the module that
    declared the class, so several claims below need a module whose contents
    they control. `dont_inherit` is load-bearing: without it the nested compile
    inherits this module's `from __future__ import annotations` and every claim
    about evaluated annotations quietly becomes a claim about strings.
    """
    module = ModuleType(module_name)
    module.__dict__.update(names)
    sys.modules[module_name] = module
    prefix = "from __future__ import annotations\n" if postponed else ""
    exec(  # noqa: S102
        compile(prefix + source, f"<{module_name}>", "exec", dont_inherit=True),
        module.__dict__,
    )
    return module.__dict__[class_name]


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
        AnnotationTarget, on_delete=postgres.CASCADE
    )
    backup: AnnotationTarget | None = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        AnnotationTarget,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
    )


class FieldAnnotated(Model):
    model_options = postgres.Options(package_label="examples")

    owner: Field[AnnotationTarget] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
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

    owner = types.ForeignKeyField(AnnotationTarget, on_delete=postgres.CASCADE)


def test_no_registered_model_annotates_a_foreign_key_as_a_value():
    """Every model in the test app's registry -- the example fixtures plus the
    first-party package models they pull in -- annotates its foreign keys
    `Field[...]`, so the check is silent."""
    results = CheckForeignKeyAnnotatedAsValue().run()
    assert not results, "Foreign keys annotated as values:\n" + "\n".join(
        r.fix for r in results
    )


def test_reports_every_foreign_key_annotated_with_the_related_model():
    assert foreign_keys_annotated_as_values(ValueAnnotated) == [
        ("backup", "AnnotationTarget"),
        ("owner", "AnnotationTarget"),
    ]


def test_a_field_annotation_clears_the_foreign_key():
    assert foreign_keys_annotated_as_values(FieldAnnotated) == []


def test_an_unannotated_foreign_key_is_not_this_checks_story():
    """An unannotated field isn't a constructor argument at all -- that's
    `postgres.field_leaks_into_constructor`'s counterpart in
    CheckTypedConstruction, not a wrong annotation."""
    assert foreign_keys_annotated_as_values(Unannotated) == []


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
    assert "'owner: Field[AnnotationTarget] = ...'" in fixes
    assert "'backup: Field[AnnotationTarget | None] = ...' with default=None" in fixes
    assert "TYPE_CHECKING" in fixes


# ---------------------------------------------------------------------------
# Where the annotation is declared
# ---------------------------------------------------------------------------


class OrdinaryMixin:
    """A plain Python mixin -- no `postgres.ModelMixin`, so PEP 681 leaves its
    fields out of the synthesized constructor. It still *types the attribute*,
    which is all this check cares about."""

    # No dataclass transform here, so ty runs the ordinary assignment check and
    # catches the spelling. On a model it stays silent -- which is the gap this
    # preflight check covers.
    owner: AnnotationTarget = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class UsesOrdinaryMixin(OrdinaryMixin, Model):
    model_options = postgres.Options(package_label="examples")


class ValueAnnotatedMixin(ModelMixin):
    owner: AnnotationTarget = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class ReannotatesTheMixinField(ValueAnnotatedMixin, Model):
    model_options = postgres.Options(package_label="examples")

    owner: Field[AnnotationTarget] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


def test_an_ordinary_mixins_annotation_is_read_too():
    """The transform gates the *constructor* checks, where PEP 681 really does
    ignore a transformless base. It has nothing to say about attribute types:
    a plain mixin types `UsesOrdinaryMixin.owner` exactly as a model would."""
    assert foreign_keys_annotated_as_values(UsesOrdinaryMixin) == [
        ("owner", "AnnotationTarget")
    ]


def test_the_nearest_annotation_in_the_mro_is_the_one_read():
    """The checker reads the subclass's annotation, so a subclass that fixes a
    mixin's spelling clears the field rather than reporting it twice."""
    assert foreign_keys_annotated_as_values(ReannotatesTheMixinField) == []


# ---------------------------------------------------------------------------
# Spellings that mean `Field`, and must stay silent
# ---------------------------------------------------------------------------


class AliasAnnotated(Model):
    """`Field` under an import alias is the same class, so it reads the same."""

    model_options = postgres.Options(package_label="examples")

    owner: AliasedField[AnnotationTarget] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class ClassVarAnnotated(Model):
    """`ClassVar[...]` is the declared way to keep an attribute out of the
    constructor, so it isn't this check's business -- and `Field[ClassVar[...]]`
    would be a nonsense repair to suggest."""

    model_options = postgres.Options(package_label="examples")

    owner: ClassVar[Field[AnnotationTarget]] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class TypeOnlyFieldImport(Model):
    """The common app spelling: postponed annotations, `Field` imported only
    under `if TYPE_CHECKING:`. The name is absent at runtime, so nothing can be
    established -- and nothing is said."""

    model_options = postgres.Options(package_label="examples")

    owner: TypeOnlyField[AnnotationTarget] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class AliasedFieldType(Model):
    """A `type` alias resolves to a `TypeAliasType`, not a class."""

    model_options = postgres.Options(package_label="examples")

    owner: FieldAlias = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class AnnotatedField(Model):
    model_options = postgres.Options(package_label="examples")

    owner: Annotated[Field[AnnotationTarget], "documented"] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


class AnnotatedValue(Model):
    model_options = postgres.Options(package_label="examples")

    owner: Annotated[AnnotationTarget, "documented"] = types.ForeignKeyField(
        AnnotationTarget, on_delete=postgres.CASCADE
    )


def test_an_import_alias_for_field_is_recognized():
    """Recognition resolves the annotation's head against the declaring
    module, so it follows aliases instead of matching on the spelling."""
    assert foreign_keys_annotated_as_values(AliasAnnotated) == []


def test_a_classvar_annotation_is_left_alone():
    assert foreign_keys_annotated_as_values(ClassVarAnnotated) == []


def test_a_type_checking_only_field_import_is_silent():
    """The one that used to misfire: `Field` unresolvable at runtime was read
    as "not a Field" and warned, recommending `Field[Field[Target] | None]`."""
    assert "TypeOnlyField" not in dir(sys.modules[__name__])
    assert foreign_keys_annotated_as_values(TypeOnlyFieldImport) == []


def test_a_type_alias_for_a_field_is_silent():
    assert foreign_keys_annotated_as_values(AliasedFieldType) == []


def test_an_annotated_wrapper_around_a_field_is_silent():
    assert foreign_keys_annotated_as_values(AnnotatedField) == []


def test_an_annotated_wrapper_around_the_model_still_warns():
    """Unwrapping cuts both ways: `Annotated[...]` is peeled off before the
    verdict, so wrapping the wrong annotation doesn't hide it."""
    assert foreign_keys_annotated_as_values(AnnotatedValue) == [
        ("owner", "AnnotationTarget")
    ]


# ---------------------------------------------------------------------------
# Shapes that must not crash, and must not guess
# ---------------------------------------------------------------------------

_HOSTILE = ModuleType("tests.hostile_namespace")


def _hostile_getattr(name: str) -> Any:
    raise RuntimeError(f"this namespace objects to being probed for {name!r}")


# A module-level `__getattr__`, the PEP 562 hook a lazy-import namespace uses.
_HOSTILE.__dict__["__getattr__"] = _hostile_getattr
sys.modules[_HOSTILE.__name__] = _HOSTILE

HostileAnnotation = _class_in_module(
    "tests.fk_annotation_hostile",
    "HostileAnnotation",
    "class HostileAnnotation(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    owner: hostile.Field[AnnotationTarget] = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n",
    postponed=True,
    Model=Model,
    types=types,
    postgres=postgres,
    AnnotationTarget=AnnotationTarget,
    hostile=_HOSTILE,
)

MalformedAnnotation = _class_in_module(
    "tests.fk_annotation_malformed",
    "MalformedAnnotation",
    "class MalformedAnnotation(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    owner: AnnotationTarget = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n",
    postponed=True,
    Model=Model,
    types=types,
    postgres=postgres,
    AnnotationTarget=AnnotationTarget,
)
# Nothing you can write in Python produces this, so it's installed directly --
# the point is only that a string the check can't parse leaves it silent rather
# than emitting a rewrite built from half of it.
MalformedAnnotation.__annotations__ = {"owner": "AnnotationTarget["}


class DoubledOptional(Model):
    """`Optional[X | None]` collapses at runtime but survives as written text."""

    model_options = postgres.Options(package_label="examples")

    owner: None | AnnotationTarget = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        AnnotationTarget,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
    )


def test_a_module_that_raises_on_attribute_access_is_silent():
    """Resolution is a probe of someone else's namespace, and a namespace is
    allowed to object. Preflight must never traceback on an annotation."""
    assert foreign_keys_annotated_as_values(HostileAnnotation) == []


def test_an_unbalanced_annotation_is_silent():
    assert foreign_keys_annotated_as_values(MalformedAnnotation) == []


def test_a_doubled_optional_warns_with_a_valid_rewrite():
    """It still names the related model, so it still warns -- and the rewrite
    is built from the field, so the doubled `| None` can't reach the message."""
    assert foreign_keys_annotated_as_values(DoubledOptional) == [
        ("owner", "AnnotationTarget")
    ]
    fix = foreign_key_annotation_results(DoubledOptional)[0].fix
    assert "'owner: Field[AnnotationTarget | None] = ...' with default=None" in fix
    assert "None | None" not in fix


# ---------------------------------------------------------------------------
# Where the related model's name is the only evidence
# ---------------------------------------------------------------------------

TypeOnlyModelImport = _class_in_module(
    "tests.fk_annotation_type_only_model",
    "TypeOnlyModelImport",
    "class TypeOnlyModelImport(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    owner: AnnotationTarget = types.ForeignKeyField(\n"
    "        _target, on_delete=postgres.CASCADE\n"
    "    )\n",
    postponed=True,
    Model=Model,
    types=types,
    postgres=postgres,
    # The target is reachable under a private name so the field can be built,
    # while the *annotation's* name is absent -- which is what a
    # `if TYPE_CHECKING: from app.users.models import User` module looks like
    # at runtime.
    _target=AnnotationTarget,
)

EvaluatedAnnotations = _class_in_module(
    "tests.fk_annotation_evaluated",
    "EvaluatedAnnotations",
    "class EvaluatedAnnotations(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    owner: AnnotationTarget = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n"
    "    backup: AnnotationTarget | None = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.SET_NULL,\n"
    "        allow_null=True, required=False, default=None,\n"
    "    )\n"
    "    documented: Annotated[Field[AnnotationTarget], 'x'] = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n"
    "    aliased: FieldAlias = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n"
    "    wrapped: Annotated[AnnotationTarget, 'x'] = types.ForeignKeyField(\n"
    "        AnnotationTarget, on_delete=postgres.CASCADE\n"
    "    )\n",
    postponed=False,
    Model=Model,
    types=types,
    postgres=postgres,
    Field=Field,
    Annotated=Annotated,
    FieldAlias=FieldAlias,
    AnnotationTarget=AnnotationTarget,
)


def test_the_related_model_name_is_matched_even_when_it_cannot_be_imported():
    """The case the check exists for: a framework package naming the app's
    `User` by string, with the class imported only for typing. The annotation
    resolves to nothing, so the field's own related model is the evidence."""
    assert foreign_keys_annotated_as_values(TypeOnlyModelImport) == [
        ("owner", "AnnotationTarget")
    ]


def test_an_evaluated_class_annotation_yields_a_valid_rewrite():
    """With annotations evaluated, `str()` renders a class as
    `<class 'tests...AnnotationTarget'>` -- which has no business in a message
    telling someone what to type. The rewrite comes from the field instead."""
    assert EvaluatedAnnotations.__annotations__["owner"] is AnnotationTarget

    assert foreign_keys_annotated_as_values(EvaluatedAnnotations) == [
        ("backup", "AnnotationTarget"),
        ("owner", "AnnotationTarget"),
        # `Annotated[...]` is peeled off an evaluated annotation too.
        ("wrapped", "AnnotationTarget"),
    ]
    fixes = {
        str(r.obj).rsplit(".", 1)[-1]: r.fix
        for r in foreign_key_annotation_results(EvaluatedAnnotations)
    }
    assert "<class" not in fixes["owner"]
    assert "<class" not in fixes["backup"]
    assert "'owner: Field[AnnotationTarget] = ...'" in fixes["owner"]
    assert "default=None" not in fixes["owner"]
    assert (
        "'backup: Field[AnnotationTarget | None] = ...' with default=None"
        in fixes["backup"]
    )


def test_evaluated_wrappers_around_a_field_are_unwrapped():
    """`documented` and `aliased` are absent from the report above: an
    evaluated `Annotated[...]` and a `TypeAliasType` both peel down to
    `Field[...]`."""
    reported = dict(foreign_keys_annotated_as_values(EvaluatedAnnotations))
    assert "documented" not in reported
    assert "aliased" not in reported
