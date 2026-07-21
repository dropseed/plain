"""Keeping a shared database safe from a branch's migrations.

Forking is the default, so most checkouts own their database outright and none
of this applies. But `plain db use` deliberately points several checkouts at one
database, and that's where the sharp edge is: applying a branch-only migration
to a shared database mutates the schema that main — and every other sharer —
depends on.

Drift and corruption are not symmetric. A stale fork is benign; you re-fork it.
A shared database with someone else's half-finished migration in it is not
something you can undo. So when divergence is about to happen, we fork instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .cluster import Cluster
from .identity import (
    database_name_for_checkout,
    project_identity,
    resolve_database_name,
    write_pointer,
)
from .resolve import current_branch, is_managed, open_cluster, write_cached_url
from .schema_state import pending_migration_count


def database_is_shared(cluster: Cluster, db_name: str, current_checkout: str) -> bool:
    """True when the database's metadata names a *different* checkout as owner."""
    metadata = cluster.get_metadata(db_name) or {}
    owner = metadata.get("checkout")
    return bool(owner) and owner != current_checkout


def guard_shared_database(
    project_root: Path,
    cluster: Cluster,
    db_name: str,
    *,
    interactive: bool = True,
) -> str:
    """Return the database this checkout should actually use.

    A no-op unless the database is shared *and* this branch has migrations it
    hasn't applied. Non-interactively we fork, which is the choice that can't
    damage anyone else's data — the right default for CI and for agents.
    """
    current = str(project_root.resolve())
    if not database_is_shared(cluster, db_name, current):
        return db_name
    if pending_migration_count(cluster.url(db_name)) == 0:
        return db_name  # shared, but nothing divergent to apply

    owner = (cluster.get_metadata(db_name) or {}).get("checkout", "?")
    project_name, _ = project_identity(project_root)
    fork_name = database_name_for_checkout(project_name, project_root)

    choice = "f"
    if interactive and sys.stdin.isatty():
        click.secho(
            f"⚠ Database {db_name!r} is shared (owned by {owner}) and this "
            f"branch adds migrations it doesn't have.",
            fg="yellow",
        )
        choice = click.prompt(
            "  [f]ork to your own copy and apply / [a]pply to the shared database / [c]ancel",
            default="f",
        ).lower()[:1]

    if choice == "c":
        raise SystemExit("Cancelled — shared database left untouched.")
    if choice == "a":
        return db_name

    # This checkout may still own the database it had before it was pointed at
    # the shared one. Going back to it is better than forking over the top of
    # it: no data is destroyed, and `postgres sync` brings its schema current.
    if cluster.database_exists(fork_name):
        write_pointer(project_root, fork_name)
        click.secho(
            f"Went back to {fork_name!r} — this checkout's own database — "
            f"leaving {db_name!r} untouched.",
            fg="green",
        )
        return fork_name

    mechanism = cluster.fork_database(db_name, fork_name)
    cluster.set_metadata(
        fork_name,
        {
            "checkout": current,
            "branch": current_branch(project_root),
            "created_via": f"fork:guard:{mechanism}",
        },
    )
    write_pointer(project_root, fork_name)
    click.secho(
        f"Forked {db_name!r} → {fork_name!r}; this checkout now uses it.",
        fg="green",
    )
    return fork_name


def guard_dev_database(project_root: Path) -> str | None:
    """Dev-flow entry point. Returns a replacement URL if it forked, else None.

    Only ever acts on a database we manage — a bring-your-own database is never
    touched, because it has no metadata saying we own it and no sentinel set.
    """
    if not is_managed(project_root):
        return None

    cluster = open_cluster(project_root, create=False)
    if cluster is None:
        return None

    db_name = resolve_database_name(project_root)
    new_name = guard_shared_database(project_root, cluster, db_name, interactive=True)
    if new_name == db_name:
        return None

    url = cluster.url(new_name)
    write_cached_url(project_root, url)
    return url
