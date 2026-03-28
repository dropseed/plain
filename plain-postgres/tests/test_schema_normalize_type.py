from __future__ import annotations

import pytest

from plain.postgres import fields
from plain.postgres.fields.json import JSONField

# Postgres short-form type aliases that should NOT appear in db_type() output.
_SHORT_ALIASES = {
    "bool",
    "varchar",
    "int2",
    "int4",
    "int8",
    "float4",
    "float8",
    "serial",
    "bigserial",
    "smallserial",
    "timestamptz",
    "timetz",
}

# All concrete field classes and their expected db_type_sql values
_FIELD_TYPES = [
    (fields.BooleanField, "boolean"),
    (fields.DateField, "date"),
    (fields.DateTimeField, "timestamp with time zone"),
    (fields.DecimalField, "numeric(%(max_digits)s,%(decimal_places)s)"),
    (fields.DurationField, "interval"),
    (fields.FloatField, "double precision"),
    (fields.IntegerField, "integer"),
    (fields.BigIntegerField, "bigint"),
    (fields.SmallIntegerField, "smallint"),
    (fields.GenericIPAddressField, "inet"),
    (fields.TextField, "text"),
    (fields.TimeField, "time without time zone"),
    (fields.UUIDField, "uuid"),
    (fields.BinaryField, "bytea"),
    (fields.PrimaryKeyField, "bigint"),
    (fields.PositiveIntegerField, "integer"),
    (fields.PositiveBigIntegerField, "bigint"),
    (fields.PositiveSmallIntegerField, "smallint"),
    (JSONField, "jsonb"),
]


@pytest.mark.parametrize(
    ("field_class", "expected_sql"),
    _FIELD_TYPES,
    ids=[cls.__name__ for cls, _ in _FIELD_TYPES],
)
def test_db_type_sql_set(field_class: type[fields.Field], expected_sql: str) -> None:
    """Every concrete field class has db_type_sql set correctly."""
    assert field_class.db_type_sql == expected_sql


@pytest.mark.parametrize(
    ("field_class", "expected_sql"),
    _FIELD_TYPES,
    ids=[cls.__name__ for cls, _ in _FIELD_TYPES],
)
def test_db_type_uses_canonical_form(field_class: type, expected_sql: str) -> None:
    """db_type_sql should use Postgres canonical type names, not short aliases."""
    base = expected_sql.split("(")[0].split()[0]
    assert base not in _SHORT_ALIASES, (
        f"{field_class.__name__}.db_type_sql = {expected_sql!r} uses short alias {base!r}. "
        f"Use the canonical Postgres form instead."
    )


# Verify specific db_type() output matches Postgres format_type()
@pytest.mark.parametrize(
    ("field_class", "expected"),
    [
        (fields.DateTimeField, "timestamp with time zone"),
        (fields.TimeField, "time without time zone"),
        (fields.FloatField, "double precision"),
        (fields.BooleanField, "boolean"),
        (fields.IntegerField, "integer"),
        (fields.BigIntegerField, "bigint"),
        (fields.SmallIntegerField, "smallint"),
        (fields.TextField, "text"),
        (fields.UUIDField, "uuid"),
        (fields.DateField, "date"),
        (fields.DurationField, "interval"),
        (fields.BinaryField, "bytea"),
        (fields.PrimaryKeyField, "bigint"),
    ],
    ids=lambda x: x.__name__ if isinstance(x, type) else x,
)
def test_specific_type_matches_canonical(field_class: type, expected: str) -> None:
    f = field_class()
    assert f.db_type() == expected
