from __future__ import annotations

# PostgreSQL creation is now defined in BaseDatabaseCreation since
# PostgreSQL is the only supported database. This module exists for compatibility.
from plain.models.backends.base.creation import BaseDatabaseCreation

DatabaseCreation = BaseDatabaseCreation
