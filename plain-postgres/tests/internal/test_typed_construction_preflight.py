"""The typed-construction conformance preflight.

`@dataclass_transform` on `ModelBase` turns every annotated, non-`ClassVar`
attribute into a synthesized constructor parameter. If such an attribute isn't a
real field, the type checker accepts `Model(that=...)` while the runtime rejects
it -- an unsound divergence no ordinary test exercises (nobody writes
`Model(model_options=...)`). `CheckTypedConstruction` re-derives the synthesized
field set and asserts each entry is a real field.

This runs the check against the live test-app registry (every example fixture
model), so a fixture that mis-declares an accessor as a field fails here.
"""

from __future__ import annotations

from plain.postgres.preflight import CheckTypedConstruction


def test_no_model_leaks_an_accessor_into_its_constructor():
    results = CheckTypedConstruction().run()
    leaks = [r.fix for r in results if r.id == "postgres.field_leaks_into_constructor"]
    assert not leaks, (
        "Non-field attributes leaked into the typed constructor:\n" + "\n".join(leaks)
    )
