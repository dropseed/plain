"""
PostgreSQL database schema editor.

PostgreSQL is the only supported database, so the base class contains
all PostgreSQL-specific implementation. This module provides the
DatabaseSchemaEditor alias for compatibility.
"""

from plain.models.backends.base.schema import BaseDatabaseSchemaEditor

DatabaseSchemaEditor = BaseDatabaseSchemaEditor
