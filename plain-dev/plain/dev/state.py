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

# `find_project_root` and `checkout_state_path` live in `plain.runtime` now —
# every `.plain` consumer (not just plain-dev) needs to agree on the project
# root and on where a checkout's facts (as opposed to artifacts) are kept.
# Re-exported here so existing callers in this package don't all need to
# change their imports.
from plain.runtime import checkout_id, checkout_state_path, find_project_root

__all__ = [
    "checkout_id",
    "checkout_state_path",
    "find_project_root",
    "sanitize",
    "short_digest",
]


def sanitize(value: str) -> str:
    """Lowercase and reduce to `[a-z0-9_]`."""
    return "".join(c if c.isalnum() else "_" for c in value.lower()).strip("_")


def short_digest(value: str) -> str:
    """A short, stable hash for disambiguating names built from `value`."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]
