"""Tests for POSTGRES_MANAGEMENT_URL and use_management_connection()."""

from __future__ import annotations

import pytest

from plain.postgres.connections import _db_conn, use_management_connection
from plain.runtime import settings


@pytest.fixture(autouse=True)
def _reset_db_conn():
    token = _db_conn.set(None)
    yield
    _db_conn.reset(token)


@pytest.fixture(autouse=True)
def _reset_management_url():
    original = settings.POSTGRES_MANAGEMENT_URL
    yield
    settings.POSTGRES_MANAGEMENT_URL = original


def test_default_management_url_is_empty():
    """POSTGRES_MANAGEMENT_URL defaults to empty string."""
    assert str(settings.POSTGRES_MANAGEMENT_URL) == ""


def test_context_manager_falls_back_to_postgres_url_when_management_unset(
    isolated_db,
):
    """When POSTGRES_MANAGEMENT_URL is unset, the context manager uses POSTGRES_URL."""
    assert str(settings.POSTGRES_MANAGEMENT_URL) == ""

    with use_management_connection() as conn:
        # Connection opens against POSTGRES_URL — database name matches.
        conn.ensure_connection()
        expected_db = conn.settings_dict["DATABASE"]
        assert expected_db  # Sanity check: a real database was opened.


def test_context_manager_uses_management_url_when_set(isolated_db):
    """When POSTGRES_MANAGEMENT_URL is set, the context manager opens against it."""
    from plain.postgres.database_url import (
        build_database_url,
        parse_database_url,
    )

    # Point management URL at a nonexistent database — connection should fail,
    # proving the management URL was used (not POSTGRES_URL).
    parts = parse_database_url(str(settings.POSTGRES_URL))
    parts["DATABASE"] = "this_database_does_not_exist_xyz"
    settings.POSTGRES_MANAGEMENT_URL = build_database_url(parts)

    import psycopg

    with pytest.raises(psycopg.OperationalError):
        with use_management_connection() as conn:
            conn.ensure_connection()


def test_context_manager_reuses_active_connection_when_management_url_unset(
    isolated_db,
):
    """When POSTGRES_MANAGEMENT_URL is unset, the active connection is reused."""
    from plain.postgres.connections import get_connection

    outer = get_connection()
    with use_management_connection() as inside:
        assert inside is outer
        assert get_connection() is outer


def test_context_manager_swaps_active_connection(isolated_db):
    """When POSTGRES_MANAGEMENT_URL differs, a new connection is used inside the block."""
    from plain.postgres.connections import get_connection

    # Make the management URL distinct from POSTGRES_URL so a new connection opens.
    settings.POSTGRES_MANAGEMENT_URL = (
        str(settings.POSTGRES_URL) + "?application_name=plain_mgmt"
    )

    outer = get_connection()
    with use_management_connection() as mgmt:
        inside = get_connection()
        assert inside is mgmt
        assert inside is not outer

    # After exit, the original connection is restored.
    assert get_connection() is outer


def test_context_manager_closes_management_connection_on_exit(isolated_db):
    """The management connection is closed when the block exits."""
    settings.POSTGRES_MANAGEMENT_URL = (
        str(settings.POSTGRES_URL) + "?application_name=plain_mgmt"
    )

    with use_management_connection() as mgmt:
        mgmt.ensure_connection()
        assert mgmt.connection is not None

    # After exit, the connection is closed.
    assert mgmt.connection is None or mgmt.connection.closed
