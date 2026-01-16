from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper


class DatabaseFeatures:
    """
    Database features and configuration for PostgreSQL.
    """

    # PostgreSQL 12+ is required
    minimum_database_version: tuple[int, ...] = (12,)

    # Default value returned by cursor.fetchmany() when no rows are available
    empty_fetchmany_value: list = []

    # PostgreSQL EXPLAIN output formats
    supported_explain_formats: set[str] = {"JSON", "TEXT", "XML", "YAML"}

    def __init__(self, connection: DatabaseWrapper):
        self.connection = connection
