"""The typed-construction conformance checks.

`@dataclass_transform` on `ModelBase` turns every annotated, non-`ClassVar`
attribute into a synthesized constructor parameter. If such an attribute isn't a
real field, the type checker accepts `Model(that=...)` while the runtime rejects
it -- an unsound divergence no ordinary test exercises (nobody writes
`Model(model_options=...)`). `CheckTypedConstruction` re-derives the synthesized
field set and asserts each entry is a real field.

`CheckTypedConstruction` is deliberately NOT a registered preflight check (raw
annotations are too fragile to detect leaks robustly in arbitrary user code), so
we invoke it directly here against the live test-app registry (every example
fixture model). A fixture that mis-declares an accessor as a field fails here.
"""

from __future__ import annotations

from plain.postgres import types
from plain.postgres.base import ModelBase
from plain.postgres.preflight import CheckTypedConstruction


def test_no_model_leaks_an_accessor_into_its_constructor():
    results = CheckTypedConstruction().run()
    leaks = [r.fix for r in results if r.id == "postgres.field_leaks_into_constructor"]
    assert not leaks, (
        "Non-field attributes leaked into the typed constructor:\n" + "\n".join(leaks)
    )


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
