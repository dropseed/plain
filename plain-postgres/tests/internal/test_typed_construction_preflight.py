"""The typed-construction conformance checks.

`@dataclass_transform` on `ModelBase` turns every annotated, non-`ClassVar`
attribute into a synthesized constructor parameter. If such an attribute isn't a
real field, the type checker accepts `Model(that=...)` while the runtime rejects
it -- an unsound divergence no ordinary test exercises (nobody writes
`Model(model_options=...)`). `CheckTypedConstruction` re-derives the synthesized
field set and asserts each entry is a real field.

The mirror image is a field declared on a mixin that doesn't inherit
`postgres.ModelMixin`: the runtime collects it off the MRO, the checker never
sees it, and valid code is rejected. `CheckTypedConstruction` reports that too.

`CheckTypedConstruction` is deliberately NOT a registered preflight check (raw
annotations are too fragile to detect leaks robustly in arbitrary user code), so
we invoke it directly here against the live test-app registry (every example
fixture model). A fixture that mis-declares an accessor as a field fails here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plain.postgres import Field, ModelMixin, types
from plain.postgres.base import Model, ModelBase
from plain.postgres.preflight.models import (
    CheckTypedConstruction,
    mixin_fields_hidden_from_constructor,
)


def test_no_model_leaks_an_accessor_into_its_constructor():
    results = CheckTypedConstruction().run()
    leaks = [r.fix for r in results if r.id == "postgres.field_leaks_into_constructor"]
    assert not leaks, (
        "Non-field attributes leaked into the typed constructor:\n" + "\n".join(leaks)
    )


def test_no_model_hides_a_mixin_field_from_its_constructor():
    results = CheckTypedConstruction().run()
    hidden = [
        r.fix for r in results if r.id == "postgres.field_hidden_from_constructor"
    ]
    assert not hidden, "Mixin fields missing from the typed constructor:\n" + "\n".join(
        hidden
    )


def test_model_mixin_carries_the_same_transform_models_get():
    """ModelMixin repeats ModelBase's `@dataclass_transform` arguments, because
    PEP 681 requires a tuple literal there (mypy rejects a shared constant).
    A mixin's fields must be synthesized exactly like a model's, so the two
    declarations have to stay identical -- and ModelMixin must stay an ordinary
    class, or everything asking whether a class is a model sees mixins too.
    """
    # ty doesn't model the PEP 681 runtime dunder statically.
    assert (
        ModelMixin.__dataclass_transform__  # ty: ignore[unresolved-attribute]
        == ModelBase.__dataclass_transform__  # ty: ignore[unresolved-attribute]
    )
    assert not isinstance(ModelMixin, ModelBase)


# Unregistered on purpose -- these exist to be inspected, not to hit a database.
class PlainMixin:
    shared: Field[str] = types.TextField(max_length=10)


class UsesPlainMixin(PlainMixin, Model):
    name: Field[str] = types.TextField(max_length=10)


class TransformedMixin(ModelMixin):
    shared: Field[str] = types.TextField(max_length=10)


class UsesModelMixin(TransformedMixin, Model):
    name: Field[str] = types.TextField(max_length=10)


if TYPE_CHECKING:
    # The type-level half of the fix, checked by `uv run ty check` rather than
    # pytest: a ModelMixin field is a constructor parameter like any other. The
    # same call against UsesPlainMixin is an unknown-argument error, which is
    # what mixin_fields_hidden_from_constructor reports at runtime.
    UsesModelMixin(name="n", shared="s")


def test_field_on_a_plain_mixin_is_reported_as_hidden():
    assert mixin_fields_hidden_from_constructor(UsesPlainMixin) == [
        ("shared", "PlainMixin")
    ]


def test_field_on_a_model_mixin_is_not_hidden():
    assert mixin_fields_hidden_from_constructor(UsesModelMixin) == []


def test_dataclass_transform_field_specifiers_match_exported_fields():
    """`@dataclass_transform(field_specifiers=...)` must list every field
    constructor `types` exports. If a new field type is added to `types` but not
    here, the type checker silently stops honoring its `default=`/`init=False`
    semantics (it treats the call as a plain default value) -- no error, just
    wrong constructor typing. This pins the two lists together.
    """
    # __dataclass_transform__ is the PEP 681 runtime dunder the decorator sets;
    # ty doesn't model it statically.
    transform = ModelBase.__dataclass_transform__  # ty: ignore[unresolved-attribute]
    specifiers = {f.__name__ for f in transform["field_specifiers"]}
    # The non-`*Field` exports are reverse-relation accessors / managers, which
    # are never constructor fields (declared `ClassVar`), so they're excluded.
    exported_fields = {name for name in types.__all__ if name.endswith("Field")}
    assert specifiers == exported_fields, (
        "field_specifiers in ModelBase's @dataclass_transform is out of sync with "
        "the field constructors exported by plain.postgres.types:\n"
        f"  missing from field_specifiers: {sorted(exported_fields - specifiers)}\n"
        f"  stale in field_specifiers: {sorted(specifiers - exported_fields)}"
    )
