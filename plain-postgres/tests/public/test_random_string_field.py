"""Tests for RandomStringField and the RandomString expression it renders."""

from __future__ import annotations

import pytest
from app.examples.models.defaults import DBDefaultsExample

from plain.postgres import RandomStringField, get_connection
from plain.postgres.functions.random import RandomString


class TestRandomStringInit:
    def test_rejects_zero_length(self):
        with pytest.raises(ValueError, match=">= 1"):
            RandomString(length=0)

    def test_rejects_negative_length(self):
        with pytest.raises(ValueError, match=">= 1"):
            RandomString(length=-1)


class TestRandomStringFieldInit:
    def test_deconstruct_serializes_length(self):
        f = RandomStringField(length=10)
        _, _, _, kwargs = f.deconstruct()
        assert kwargs == {"length": 10}

    def test_has_db_default_expression(self):
        f = RandomStringField(length=16)
        expr = f.get_db_default_expression()
        assert isinstance(expr, RandomString)
        assert expr.length == 16


class TestRandomStringSQL:
    """Pin the exact SQL shape so a refactor that breaks the slicing math
    fails loudly instead of silently changing the persisted DEFAULT."""

    def _sql(self, length: int) -> str:
        from plain.postgres.ddl import compile_database_default_sql

        return compile_database_default_sql(RandomString(length=length))

    def test_short_length_uses_single_uuid_slice(self):
        assert (
            self._sql(16) == "substr(replace(gen_random_uuid()::text, '-', ''), 1, 16)"
        )

    def test_exact_uuid_length_uses_single_uuid_slice(self):
        assert (
            self._sql(32) == "substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
        )

    def test_over_uuid_length_concats_uuid_slices(self):
        assert self._sql(40) == (
            "(substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
            " || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8))"
        )

    def test_multiple_full_uuids(self):
        assert self._sql(64) == (
            "(substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
            " || substr(replace(gen_random_uuid()::text, '-', ''), 1, 32))"
        )


class TestRandomStringRoundTrip:
    """The field's SQL must match what Postgres stores in pg_get_expr so
    convergence sees no drift after sync."""

    def test_value_populated_on_create(self, db):
        row = DBDefaultsExample.query.create(name="r")
        assert isinstance(row.token, str)
        assert len(row.token) == 16

    def test_values_are_unique(self, db):
        rows = DBDefaultsExample.query.bulk_create(
            [DBDefaultsExample(name=f"r-{i}") for i in range(5)]
        )
        tokens = {r.token for r in rows}
        assert len(tokens) == 5

    def test_value_drawn_from_hex_alphabet(self, db):
        row = DBDefaultsExample.query.create(name="r")
        assert set(row.token).issubset(set("0123456789abcdef"))

    def test_column_has_persisted_default(self, db):
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT column_default
                  FROM information_schema.columns
                 WHERE table_name = %s AND column_name = %s
                """,
                ["examples_dbdefaultsexample", "token"],
            )
            row = cursor.fetchone()
        assert row is not None
        (default_sql,) = row
        assert default_sql is not None
        assert "gen_random_uuid" in default_sql
        assert "substr" in default_sql

    def test_explicit_value_overrides_default(self, db):
        row = DBDefaultsExample.query.create(name="r", token="explicit-value")
        assert row.token == "explicit-value"

    def test_raw_insert_uses_persisted_default(self, db):
        """A raw INSERT that omits `token` gets a fresh random value from the
        column DEFAULT — the point of declaring the default at the DB level."""
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO examples_dbdefaultsexample (name)
                VALUES (%s)
                RETURNING token
                """,
                ["raw"],
            )
            row = cursor.fetchone()
        assert row is not None
        (token,) = row
        assert isinstance(token, str)
        assert len(token) == 16
