"""The `postgres.nullable_field_without_default` check.

A nullable column is already omittable at runtime -- `ColumnField.get_default`
returns None for it. A type checker disagrees: PEP 681 makes a field optional in
the synthesized constructor only when the declaration passes `default=` at the
call site. So `Model()` runs and the checker calls the field missing. The check
lists the fields where the two disagree; `default=None` settles it and persists
nothing.

The models here are deliberately unregistered -- they exist to be inspected, not
to hit a database -- so they're fed to `nullable_fields_missing_default`
directly, while the registered-model sweep goes through the check itself.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from plain.postgres import Field, types
from plain.postgres.base import Model
from plain.postgres.preflight.models import (
    CheckNullableFieldWithoutDefault,
    nullable_default_results,
    nullable_fields_missing_default,
)

from plain import postgres


def test_no_registered_model_is_missing_a_nullable_default():
    """Every model in the test app's registry -- the example fixtures plus the
    first-party package models they pull in -- declares `default=None` on its
    nullable fields, so the check is silent."""
    results = CheckNullableFieldWithoutDefault().run()
    assert not results, "Nullable fields missing default=None:\n" + "\n".join(
        r.fix for r in results
    )


class MissingDefaults(Model):
    model_options = postgres.Options(package_label="examples")

    text: Field[str | None] = types.TextField(
        max_length=10, required=False, allow_null=True
    )
    number: Field[int | None] = types.IntegerField(required=False, allow_null=True)
    when: Field[datetime | None] = types.DateTimeField(required=False, allow_null=True)


class DeclaredDefaults(Model):
    model_options = postgres.Options(package_label="examples")

    text: Field[str | None] = types.TextField(
        max_length=10, required=False, allow_null=True, default=None
    )
    number: Field[int | None] = types.IntegerField(
        required=False, allow_null=True, default=None
    )
    # A ColumnField-direct field: `default=None` is validated and then
    # discarded, so only `has_declared_default()` remembers the call site.
    when: Field[datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    # A non-None default makes the field optional just as well.
    counted: Field[int] = types.IntegerField(default=0)


class DatabaseOwned(Model):
    model_options = postgres.Options(package_label="examples")

    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime | None] = types.DateTimeField(
        update_now=True, allow_null=True
    )
    token: Field[str | None] = types.RandomStringField(length=8, allow_null=True)
    uuid: Field[UUID] = types.UUIDField(generate=True)


def test_reports_every_nullable_field_without_a_declared_default():
    assert sorted(nullable_fields_missing_default(MissingDefaults)) == [
        "number",
        "text",
        "when",
    ]


def test_declared_default_clears_the_field():
    assert nullable_fields_missing_default(DeclaredDefaults) == []


def test_db_owned_fields_are_skipped():
    """These are `init=False` in the stub -- out of the constructor entirely,
    so a missing `default=` can't make them look required. The `id` primary key
    is on every model here and never reported either."""
    assert nullable_fields_missing_default(DatabaseOwned) == []


def test_results_are_warnings_that_name_the_field_and_the_fix():
    """Nothing is broken at runtime, so the check warns rather than fails."""
    results = nullable_default_results(MissingDefaults)
    assert [r.id for r in results] == ["postgres.nullable_field_without_default"] * len(
        results
    )
    assert all(r.warning for r in results)
    fixes = " ".join(r.fix for r in results)
    assert "MissingDefaults.text" in fixes
    assert "default=None" in fixes
    assert "no schema" in fixes
