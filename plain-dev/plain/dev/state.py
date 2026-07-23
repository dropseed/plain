"""Which checkout am I, and where does its state live?

A checkout accumulates facts about itself: which database it uses, whether its
dev server is running. Those facts are *about* the checkout but they don't
belong *inside* it — a working tree is exactly what gets symlinked, copied,
rsynced, and mounted into containers, so state keyed by location is eventually
read by the wrong reader. Two worktrees sharing a `.plain/` then quietly share
a database, or one refuses to start because the other's dev server holds the
pidfile.

So the checkout's path is the key, and the state lives beside the rest of
Plain's machine-level cache. Artifacts stay in `.plain/` — logs you tail,
compiled assets, certificates. The difference is that an artifact read from the
wrong place is confusing, while a *fact* read from the wrong place is wrong.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from plain.runtime import PLAIN_CACHE_PATH

from .utils import has_pyproject_toml


def sanitize(value: str) -> str:
    """Lowercase and reduce to `[a-z0-9_]`."""
    return "".join(c if c.isalnum() else "_" for c in value.lower()).strip("_")


def short_digest(value: str) -> str:
    """A short, stable hash for disambiguating names built from `value`."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def find_project_root(start: Path) -> Path:
    """The nearest directory at or above `start` holding a pyproject.toml.

    One definition, used by the CLI (which starts from the app), by `setup()`
    (which starts from the working directory), and by the dev supervisors,
    because they have to agree: the project root decides the database name, the
    cluster identity, and where this checkout's state lives. Two answers means
    two checkouts.
    """
    for directory in [start, *start.parents]:
        if has_pyproject_toml(directory):
            return directory
    return start


def checkout_id(project_root: Path) -> str:
    """What "this checkout" means when we record or compare ownership.

    One definition because it's compared for exact equality against the
    database metadata `plain.dev.postgres.guard` reads, and two sites
    normalizing differently would silently disagree forever rather than fail.
    """
    return str(project_root.resolve())


def checkout_state_path(project_root: Path) -> Path:
    """Where this checkout's facts about itself are kept.

    Keyed by the checkout's resolved path (see the module docstring for why),
    with the readable checkout name in the directory too, so the cache stays
    greppable when something needs explaining.
    """
    resolved = project_root.resolve()
    return (
        PLAIN_CACHE_PATH
        / "checkouts"
        / f"{sanitize(resolved.name)}-{short_digest(str(resolved))}"
    )
