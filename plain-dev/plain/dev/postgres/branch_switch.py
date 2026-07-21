"""Noticing when you've switched branches out from under your database.

Databases record the branch they were last used on. When that changes and the
database turns out to be *ahead* of the code — carrying tables and migration
records this branch has never heard of — we say so, because nothing else will.
The app keeps working, queries keep succeeding, and the schema quietly doesn't
match the code.

We report and step aside rather than acting. Repointing someone's database
without being asked is worse than the stale schema it would fix, and the useful
remedies (`plain db fork`, `plain db use`, `plain db reset`) are one command
away once you know what happened.
"""

from __future__ import annotations

from pathlib import Path

import click

from .cluster import Cluster
from .identity import current_branch, resolve_database_name
from .resolve import is_managed, open_cluster
from .schema_state import migrations_not_on_disk


def check_branch_switch(project_root: Path) -> None:
    """Warn if this database belongs to a branch you've since left.

    Only ever looks at a database we manage, and only reports — see the module
    docstring. Never raises: this is advisory, and a failure here must not stop
    `plain dev` from starting.
    """
    if not is_managed(project_root):
        return

    cluster = open_cluster(project_root, create=False)
    if cluster is None:
        return

    db_name = resolve_database_name(project_root)
    if not cluster.database_exists(db_name):
        return

    branch = current_branch(project_root)
    metadata = cluster.get_metadata(db_name) or {}
    recorded_branch = metadata.get("branch")

    if branch and recorded_branch != branch:
        _report_if_ahead(
            cluster,
            db_name=db_name,
            previous_branch=recorded_branch,
            branch=branch,
        )
        cluster.update_metadata(db_name, branch=branch)


def _report_if_ahead(
    cluster: Cluster,
    *,
    db_name: str,
    previous_branch: str | None,
    branch: str,
) -> None:
    ahead = migrations_not_on_disk(cluster.url(db_name))
    if not ahead:
        return

    listed = ", ".join(f"{package}.{name}" for package, name in ahead[:3])
    if len(ahead) > 3:
        listed += f" (and {len(ahead) - 3} more)"

    origin = f" from {previous_branch!r}" if previous_branch else ""
    click.secho(
        f"⚠ Database {db_name!r} is ahead of this branch.",
        fg="yellow",
    )
    click.echo(
        f"  It still has {len(ahead)} migration(s){origin} that {branch!r} "
        f"doesn't have on disk: {listed}."
    )
    click.echo(
        "  Your schema has tables this branch's code doesn't know about. To get "
        "a clean one:\n"
        "    plain db fork <name> --from <main>   # a copy without those changes\n"
        "    plain db reset                       # empty, then `plain postgres sync`\n"
        "  Or keep going — nothing is broken, the schema is just wider than the code."
    )
