from __future__ import annotations

import pytest

from plain.postgres.dialect import DATA_TYPES

# Postgres short-form type aliases that should NOT appear in db_type() output.
# If db_type() returns canonical forms, none of these will match.
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


def _resolve_type(entry: object) -> str:
    """Resolve a DATA_TYPES entry to a concrete type string."""
    if isinstance(entry, str) and "%(" in entry:
        # DecimalField template
        return entry % {"max_digits": 10, "decimal_places": 2}
    if isinstance(entry, str):
        return entry
    # Callable (e.g. CharField's _get_varchar_column)
    result = entry({"max_length": 100})  # type: ignore[operator]
    assert isinstance(result, str)
    return result


@pytest.mark.parametrize(
    "field_type",
    list(DATA_TYPES.keys()),
)
def test_db_type_uses_canonical_form(field_type: str) -> None:
    """db_type() output should use Postgres canonical type names, not short aliases."""
    entry = DATA_TYPES[field_type]
    type_str = _resolve_type(entry)

    # The first word of the type should not be a known short alias
    base = type_str.split("(")[0].split()[0]
    assert base not in _SHORT_ALIASES, (
        f"{field_type} db_type() returns {type_str!r} which uses short alias {base!r}. "
        f"Use the canonical Postgres form instead."
    )


def test_varchar_without_max_length() -> None:
    """CharField without max_length should also use canonical form."""
    entry = DATA_TYPES["CharField"]
    assert callable(entry)
    type_str = entry({"max_length": None})
    assert type_str == "character varying"


def test_varchar_with_max_length() -> None:
    """CharField with max_length should use canonical form."""
    entry = DATA_TYPES["CharField"]
    assert callable(entry)
    type_str = entry({"max_length": 255})
    assert type_str == "character varying(255)"


# Verify specific types match what Postgres format_type() returns
@pytest.mark.parametrize(
    ("field_type", "expected"),
    [
        ("DateTimeField", "timestamp with time zone"),
        ("TimeField", "time without time zone"),
        ("FloatField", "double precision"),
        ("BooleanField", "boolean"),
        ("IntegerField", "integer"),
        ("BigIntegerField", "bigint"),
        ("SmallIntegerField", "smallint"),
        ("TextField", "text"),
        ("JSONField", "jsonb"),
        ("UUIDField", "uuid"),
        ("DateField", "date"),
        ("DurationField", "interval"),
        ("BinaryField", "bytea"),
        ("PrimaryKeyField", "bigint"),
    ],
)
def test_specific_type_matches_canonical(field_type: str, expected: str) -> None:
    type_str = _resolve_type(DATA_TYPES[field_type])
    assert type_str == expected
