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
(The type-level half of both claims is in `tests/typing/construction_mixins.py`.)

`CheckTypedConstruction` is deliberately NOT a registered preflight check (raw
annotations are too fragile to detect leaks robustly in arbitrary user code), so
we invoke it directly here against the live test-app registry (every example
fixture model). A fixture that mis-declares an accessor as a field fails here.
"""

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


def test_model_mixin_stays_an_ordinary_class():
    """ModelMixin carries `@dataclass_transform` but not ModelBase, so
    everything that asks whether a class is a model keeps answering no for a
    mixin. (That the two transform declarations stay identical is pinned in
    test_stub_runtime_conformance.py, alongside the rest of the field-specifier
    conformance.)"""
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


def test_field_on_a_plain_mixin_is_reported_as_hidden():
    assert mixin_fields_hidden_from_constructor(UsesPlainMixin) == [
        ("shared", "PlainMixin")
    ]


def test_field_on_a_model_mixin_is_not_hidden():
    assert mixin_fields_hidden_from_constructor(UsesModelMixin) == []
