from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.models.backends.base.base import DatabaseWrapper


class DatabaseFeatures:
    """
    Database features and configuration for PostgreSQL.

    Since Plain only supports PostgreSQL, this class contains only the
    features that are actually referenced by the codebase.
    """

    # PostgreSQL 12+ is required
    minimum_database_version: tuple[int, ...] = (12,)

    # Default value returned by cursor.fetchmany() when no rows are available
    empty_fetchmany_value: list = []

    # PostgreSQL EXPLAIN output formats
    supported_explain_formats: set[str] = {"JSON", "TEXT", "XML", "YAML"}

    # PostgreSQL window functions only support UNBOUNDED with PRECEDING/FOLLOWING
    only_supports_unbounded_with_preceding_and_following = True

    # PostgreSQL doesn't support keyword arguments in callproc
    supports_callproc_kwargs = False

    # PostgreSQL doesn't have a native XOR operator
    supports_logical_xor = False

    def __init__(self, connection: DatabaseWrapper):
        self.connection = connection
