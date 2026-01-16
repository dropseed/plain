from __future__ import annotations

# PostgreSQL introspection is now defined in BaseDatabaseIntrospection since
# PostgreSQL is the only supported database. This module exists for compatibility.
from plain.models.backends.base.introspection import (
    BaseDatabaseIntrospection,
    FieldInfo,
    TableInfo,
)

DatabaseIntrospection = BaseDatabaseIntrospection

__all__ = ["DatabaseIntrospection", "FieldInfo", "TableInfo"]
