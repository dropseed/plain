"""Postgres connection utilities for realtime."""

from __future__ import annotations


def _get_connection_string() -> str:
    """Build a psycopg connection string from Plain's database settings."""
    from plain.models.database_url import build_database_url
    from plain.runtime import settings

    return build_database_url(settings.DATABASE)
