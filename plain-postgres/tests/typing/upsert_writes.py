"""`upsert()`'s unique_fields takes a column list, so `Model.fk` belongs in it.

`Model.fk` is a `ForwardForeignKeyDescriptor` and types as `type[Related]` --
that is what makes `where()` traversal work. A column list can only mean the
foreign key column, so the element type is the union `Field[Any] | type[Model]`
and the call resolves the descriptor at runtime. `returning()` is the
opposite case and refuses it (see returning_writes.py).
"""

from __future__ import annotations

from app.examples.models.upsert import UpsertItem, UpsertScoped


def must_accept_a_foreign_key_in_the_conflict_target() -> None:
    # Runtime half:
    # tests/public/test_upsert.py::test_upsert_conflicts_on_a_foreign_key.
    scoped = UpsertScoped.query.first()
    assert scoped is not None
    UpsertScoped.query.upsert(
        tenant=scoped.tenant,
        slug="a",
        value=1,
        unique_fields=[UpsertScoped.tenant, UpsertScoped.slug],
    )


def must_accept_a_plain_column_in_the_conflict_target() -> None:
    UpsertItem.query.upsert(key="a", value=1, unique_fields=[UpsertItem.key])


def must_reject_string_field_names() -> None:
    # Runtime half:
    # tests/public/test_upsert.py::test_upsert_string_unique_field_rejected.
    UpsertItem.query.upsert(
        key="a",
        unique_fields=["key"],  # ty: ignore[invalid-argument-type]
    )
