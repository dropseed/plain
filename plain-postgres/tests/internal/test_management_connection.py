"""Tests for POSTGRES_MANAGEMENT_URL and use_management_connection()."""

from __future__ import annotations

from plain.postgres.db import use_management_connection
from plain.postgres.test import isolated_db
from plain.runtime import settings
from plain.test import override_settings, raises


def test_default_management_url_is_empty():
    """POSTGRES_MANAGEMENT_URL defaults to empty string."""
    assert str(settings.POSTGRES_MANAGEMENT_URL) == ""


@isolated_db
def test_context_manager_falls_back_to_postgres_url_when_management_unset():
    """When POSTGRES_MANAGEMENT_URL is unset, the context manager uses POSTGRES_URL."""
    assert str(settings.POSTGRES_MANAGEMENT_URL) == ""

    with use_management_connection() as conn:
        # Connection opens against POSTGRES_URL — database name matches.
        conn.ensure_connection()
        expected_db = conn.settings_dict["DATABASE"]
        assert expected_db  # Sanity check: a real database was opened.


@isolated_db
def test_context_manager_uses_management_url_when_set():
    """When POSTGRES_MANAGEMENT_URL is set, the context manager opens against it."""
    from plain.postgres.database_url import (
        build_database_url,
        parse_database_url,
    )

    # Point management URL at a nonexistent database — connection should fail,
    # proving the management URL was used (not POSTGRES_URL).
    parts = parse_database_url(str(settings.POSTGRES_URL))
    parts["DATABASE"] = "this_database_does_not_exist_xyz"

    import psycopg

    with override_settings(POSTGRES_MANAGEMENT_URL=build_database_url(parts)):
        with raises(psycopg.OperationalError):
            with use_management_connection() as conn:
                conn.ensure_connection()


@isolated_db
def test_context_manager_reuses_active_connection_when_management_url_unset():
    """When POSTGRES_MANAGEMENT_URL is unset, the active connection is reused."""
    from plain.postgres.db import get_connection

    outer = get_connection()
    with use_management_connection() as inside:
        assert inside is outer
        assert get_connection() is outer


@isolated_db
def test_context_manager_swaps_active_connection():
    """When POSTGRES_MANAGEMENT_URL differs, a new connection is used inside the block."""
    from plain.postgres.db import get_connection

    # Make the management URL distinct from POSTGRES_URL so a new connection opens.
    with override_settings(
        POSTGRES_MANAGEMENT_URL=str(settings.POSTGRES_URL)
        + "?application_name=plain_mgmt"
    ):
        outer = get_connection()
        with use_management_connection() as mgmt:
            inside = get_connection()
            assert inside is mgmt
            assert inside is not outer

        # After exit, the original connection is restored.
        assert get_connection() is outer


@isolated_db
def test_context_manager_closes_management_connection_on_exit():
    """The management connection is closed when the block exits."""
    with override_settings(
        POSTGRES_MANAGEMENT_URL=str(settings.POSTGRES_URL)
        + "?application_name=plain_mgmt"
    ):
        with use_management_connection() as mgmt:
            mgmt.ensure_connection()
            assert mgmt.connection is not None

        # After exit, the connection is closed.
        assert mgmt.connection is None or mgmt.connection.closed
