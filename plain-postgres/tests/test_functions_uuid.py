"""Tests for plain.postgres.functions.uuid."""

from __future__ import annotations

import uuid

from plain.postgres import get_connection
from plain.postgres.functions import GenRandomUUID


def test_gen_random_uuid_template():
    assert GenRandomUUID.template == "gen_random_uuid()"


def test_gen_random_uuid_produces_valid_uuid_via_raw_sql(db):
    """Sanity: Postgres understands gen_random_uuid() and it returns a UUID."""
    with get_connection().cursor() as cursor:
        cursor.execute(f"SELECT {GenRandomUUID.template}")
        row = cursor.fetchone()

    assert row is not None
    assert isinstance(row[0], uuid.UUID)


def test_gen_random_uuid_returns_distinct_values(db):
    with get_connection().cursor() as cursor:
        cursor.execute(f"SELECT {GenRandomUUID.template}, {GenRandomUUID.template}")
        row = cursor.fetchone()

    assert row is not None
    assert row[0] != row[1]
