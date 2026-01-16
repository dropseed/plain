from __future__ import annotations

from plain.models.backends.base.features import BaseDatabaseFeatures

# PostgreSQL features are defined in BaseDatabaseFeatures since PostgreSQL
# is the only supported database. This class exists for compatibility.
DatabaseFeatures = BaseDatabaseFeatures
