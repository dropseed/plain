"""`value_type=` columns: a column that round-trips a Python type.

The contract has three halves, and each is pinned here:

* the round trip — what goes in comes back out as the value type, from the
  column and from a `RETURNING` insert alike;
* the refusal — a raw primitive is a `TypeError` on every write and lookup
  path, never a silently stored string;
* the declaration — a `value_type` column is required in the typed
  constructor like any other field, and migrations never see the kwarg.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, assert_type

import pytest
from app.examples.models.value_types import Coordinates, Slug, ValueTypeExample
from plain.postgres import Field

if TYPE_CHECKING:
    # The type-level half of the contract, checked by `uv run ty check` rather
    # than pytest: the declaration's `value_type=` and the annotation's
    # `Field[X]` agree by inspection, and the field reference is the base
    # `Field[X]` — not the text-field subtype, so text-only condition methods
    # never leak onto an opaque value.
    def _value_type_declaration(row: ValueTypeExample) -> None:
        assert_type(row.slug, Slug)
        assert_type(row.location, Coordinates | None)
        assert_type(ValueTypeExample.slug, Field[Slug])
        assert_type(ValueTypeExample.location, Field[Coordinates | None])


def test_round_trips_a_text_value_type(db):
    row = ValueTypeExample(name="a", slug=Slug("hello"))
    row.create()

    reloaded = ValueTypeExample.query.get(id=row.id)
    assert isinstance(reloaded.slug, Slug)
    assert reloaded.slug == Slug("hello")


def test_round_trips_a_json_value_type(db):
    row = ValueTypeExample(name="a", slug=Slug("s"), location=Coordinates(38.9, -97.1))
    row.create()

    reloaded = ValueTypeExample.query.get(id=row.id)
    assert isinstance(reloaded.location, Coordinates)
    assert reloaded.location == Coordinates(38.9, -97.1)


def test_column_stores_the_unwrapped_value(db):
    """`to_db()` is what lands in the column — a `value_type` text column is
    still ordinary text, readable by anything that doesn't know the type."""
    from plain.postgres import get_connection

    row = ValueTypeExample(name="a", slug=Slug("hello"), location=Coordinates(1.0, 2.0))
    row.create()

    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT slug, location FROM examples_valuetypeexample WHERE id = %s",
            [row.id],
        )
        stored = cursor.fetchone()

    assert stored is not None
    assert stored[0] == "hello"
    # jsonb comes back as its text form — JSONField's own converter is what
    # decodes it, and that runs before the value type is rebuilt.
    assert json.loads(stored[1]) == {"lat": 1.0, "lon": 2.0}


def test_lookup_takes_the_value_type(db):
    ValueTypeExample(name="a", slug=Slug("hello")).create()

    assert ValueTypeExample.query.filter(slug=Slug("hello")).exists()
    assert not ValueTypeExample.query.filter(slug=Slug("other")).exists()


def test_null_value_type_column_stays_none(db):
    row = ValueTypeExample(name="a", slug=Slug("s"))
    row.create()

    reloaded = ValueTypeExample.query.get(id=row.id)
    assert reloaded.location is None


def test_instance_update_rejects_a_raw_value(db):
    row = ValueTypeExample(name="a", slug=Slug("s"))
    row.create()

    row.slug = "raw"  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError, match="takes a Slug, not a str"):
        row.update()


def test_queryset_update_rejects_a_raw_value(db):
    ValueTypeExample(name="a", slug=Slug("s")).create()

    with pytest.raises(TypeError, match="takes a Slug, not a str"):
        ValueTypeExample.query.update(slug="raw")


def test_filter_rejects_a_raw_value(db):
    with pytest.raises(TypeError, match="takes a Slug, not a str"):
        list(ValueTypeExample.query.filter(slug="raw"))


def test_json_write_rejects_a_raw_value(db):
    row = ValueTypeExample(name="a", slug=Slug("s"))
    row.create()

    row.location = {"lat": 1.0, "lon": 2.0}  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError, match="takes a Coordinates, not a dict"):
        row.update()


def test_omitting_a_value_type_column_is_a_static_error_and_a_write_error(db):
    """A `value_type` field is required in the typed constructor like any
    other field with no `default=`. The `ty: ignore` is the assertion: if the
    field ever stopped being required, ty would report the suppression as
    unused and fail the build.

    The runtime half is the write. There is no empty-string stand-in for an
    opaque value, so the omitted column holds None and the insert is refused
    rather than storing a primitive."""
    from plain.exceptions import ValidationError

    row = ValueTypeExample(name="a")  # ty: ignore[missing-argument]
    assert row.slug is None

    with pytest.raises(ValidationError, match="cannot be null"):
        row.create()


def test_migrations_never_see_the_value_type(db):
    """The column is still plain text / jsonb, so `value_type` stays out of
    `deconstruct()` — a migration file can't import the value type, and
    adding or changing one generates no migration."""
    meta = ValueTypeExample._model_meta
    _, _, _, slug_kwargs = meta.get_forward_field("slug").deconstruct()
    _, _, _, location_kwargs = meta.get_forward_field("location").deconstruct()

    assert "value_type" not in slug_kwargs
    assert "value_type" not in location_kwargs
    assert meta.get_forward_field("slug").db_type() == "text"
    assert meta.get_forward_field("location").db_type() == "jsonb"


def test_model_field_refuses_a_value_type_column():
    """Only the package owning the value type knows how to parse raw input
    into one, so a form field can't be derived — it would hand the model a
    raw string."""
    from plain.postgres.forms import model_field

    with pytest.raises(TypeError, match="declare the field explicitly"):
        model_field(ValueTypeExample.slug)
