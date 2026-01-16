from __future__ import annotations

# PostgreSQL operations are now defined in BaseDatabaseOperations since
# PostgreSQL is the only supported database. This module exists for compatibility.
from plain.models.backends.base.operations import BaseDatabaseOperations

DatabaseOperations = BaseDatabaseOperations
