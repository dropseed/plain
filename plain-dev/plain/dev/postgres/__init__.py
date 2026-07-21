"""Managed Postgres for local development.

A database URL is never required. If you configure one, we use it and stay out
of the way. If you don't, plain-dev provides one: a Postgres server per project,
and a database per checkout that starts as a copy of your main database's data.

The pieces:

- `identity` — what this project and checkout are called, and which database
  they own. All derived; the only stored state is a pointer file written when
  you explicitly reassign a checkout.
- `backends` — where the server comes from (Docker, or a local Postgres).
- `cluster` — dev's policy on top of that server: metadata and forking.
- `resolve` — whether to take over at all, and the URL if we do.
- `guard` — protecting a shared database from a branch's migrations.
"""

from .branch_switch import check_branch_switch
from .cluster import Cluster, DevDatabase
from .guard import guard_dev_database
from .identity import (
    PostgresConfig,
    cluster_name,
    database_name_for_checkout,
    project_identity,
    read_pointer,
    resolve_database_name,
    volume_name,
    write_pointer,
)
from .resolve import (
    INJECTED_URL_ENV_VAR,
    current_branch,
    ensure_database,
    ensure_postgres,
    is_managed,
    open_cluster,
    url_already_configured,
    write_cached_url,
)
from .schema_state import migrations_not_on_disk, pending_migration_count

__all__ = [
    "INJECTED_URL_ENV_VAR",
    "Cluster",
    "check_branch_switch",
    "DevDatabase",
    "PostgresConfig",
    "cluster_name",
    "current_branch",
    "database_name_for_checkout",
    "ensure_database",
    "ensure_postgres",
    "guard_dev_database",
    "is_managed",
    "open_cluster",
    "migrations_not_on_disk",
    "pending_migration_count",
    "project_identity",
    "read_pointer",
    "resolve_database_name",
    "url_already_configured",
    "volume_name",
    "write_cached_url",
    "write_pointer",
]
