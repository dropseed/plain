"""Who am I, and which database is mine?

Everything here is derived — from the directory, from git, from pyproject —
never from a registry. The only stored state is the pointer file, and it exists
only when a checkout has been deliberately repointed with `plain db use`.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ..state import checkout_id, checkout_state_path, sanitize, short_digest

MAX_NAME_LENGTH = 63  # Postgres identifier limit

# Local dev only — the cluster is bound to localhost and holds throwaway data.
DEV_USER = "postgres"
DEV_PASSWORD = "postgres"

DEFAULT_POSTGRES_IMAGE = "postgres:16"


def truncate_identifier(name: str) -> str:
    """Keep `name` inside Postgres' 63-char limit, hash-suffixing if truncated."""
    if len(name) <= MAX_NAME_LENGTH:
        return name
    return name[: MAX_NAME_LENGTH - 9] + "_" + short_digest(name)


@cache
def _git_common_dir(cwd: Path) -> str | None:
    """The shared git dir — identical for every worktree of a repo.

    Cached (along with `_git_toplevel`) because the answer can't change within
    one process, and a single cold `plain dev` start otherwise asks git the
    same question five times — cluster name, volume name, database name, and
    checkout label all derive from these two values.
    """
    return _run_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run git in `cwd`, ignoring any repository the environment points at.

    Git sets `GIT_DIR` (and friends) for hooks, so a plain command invoked from
    one — `plain pre-commit` is itself a hook — would otherwise resolve against
    the hook's repository instead of the directory we asked about. With
    `GIT_DIR` set and no work tree, `rev-parse --show-toplevel` simply fails,
    which would quietly drop us back to a less precise answer.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


@cache
def _git_toplevel(cwd: Path) -> Path | None:
    """The root of *this* worktree — differs for every checkout of a repo."""
    out = _run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(out) if out else None


def current_branch(project_root: Path) -> str | None:
    # Deliberately not cached: a long-lived `plain dev` can outlive a branch.
    return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)


def checkout_label(project_root: Path) -> str | None:
    """What distinguishes this checkout from the project's other ones.

    `None` means "this is the main checkout" (or not a git repo at all), so the
    caller should use the project name unqualified.

    Anchored on the git worktree root rather than the app directory, because an
    app often *isn't* the checkout root — `example/`, `src/`, `backend/`. Those
    directories are named identically in every worktree, so deriving from them
    would hand two checkouts the same database and let them overwrite each
    other's data. The worktree root is the thing that's actually per-checkout.
    """
    toplevel = _git_toplevel(project_root)
    if toplevel is None:
        return None

    # The main worktree is the one whose root holds the shared git dir.
    common_dir = _git_common_dir(project_root)
    if common_dir and Path(common_dir).parent.resolve() == toplevel.resolve():
        return None

    return sanitize(toplevel.name)


# What we're willing to put in a database name. Postgres itself is far more
# permissive — a quoted identifier can hold almost anything — but the name also
# has to survive being interpolated into a connection URL, where a `/` or `?`
# silently turns into a different database or a bogus query parameter. So the
# limit here is the URL's, not Postgres'.
VALID_DATABASE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_$]*$")


class InvalidDatabaseName(ValueError):
    """A name that can't be used as-is in both SQL and a connection URL."""


def validate_database_name(name: str) -> str:
    """Return `name` unchanged, or raise `InvalidDatabaseName` explaining why not.

    Checked at the boundary — every command that accepts a name from a person —
    because the failure otherwise lands far away and hard: `plain db use
    'foo?x=1'` wrote a pointer that made every subsequent command fail while
    parsing the URL, including the `plain db use` that would have undone it.
    """
    if not name:
        raise InvalidDatabaseName("Database name is empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidDatabaseName(
            f"Database name {name!r} is {len(name)} characters; "
            f"Postgres allows at most {MAX_NAME_LENGTH}."
        )
    if not VALID_DATABASE_NAME_RE.match(name):
        raise InvalidDatabaseName(
            f"Database name {name!r} must start with a letter or underscore and "
            "contain only letters, digits, underscores, or '$'."
        )
    return name


@cache  # The file can't change within one process; several call sites read it.
def read_pyproject(project_root: Path) -> dict:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    with open(pyproject, "rb") as f:
        return tomllib.load(f)


@dataclass(frozen=True)
class PostgresConfig:
    """`[tool.plain.dev.postgres]` from pyproject.toml."""

    backend: str = "auto"  # auto | docker | local | off
    image: str = DEFAULT_POSTGRES_IMAGE

    @classmethod
    def load(cls, project_root: Path) -> PostgresConfig:
        section = (
            read_pyproject(project_root)
            .get("tool", {})
            .get("plain", {})
            .get("dev", {})
            .get("postgres", {})
        )
        return cls(
            backend=str(section.get("backend", "auto")),
            image=str(section.get("image", DEFAULT_POSTGRES_IMAGE)),
        )


def project_identity(project_root: Path) -> tuple[str, str]:
    """Return `(name, hash)` identifying the project across all its worktrees.

    The hash anchors on git-common-dir, which is identical for every worktree of
    a repo. That is load-bearing, not tidiness: `CREATE DATABASE … TEMPLATE`
    only works within a single cluster, so every worktree that wants to fork
    from main must land in the same cluster.
    """
    name = project_root.name
    if project_name := read_pyproject(project_root).get("project", {}).get("name"):
        name = project_name
    name = sanitize(name)
    anchor = _git_common_dir(project_root) or checkout_id(project_root)
    return name, short_digest(anchor)


def cluster_name(project_root: Path) -> str:
    """Docker container / local-cluster identity for this project."""
    name, project_hash = project_identity(project_root)
    return f"plain-postgres-{name}-{project_hash}"


def volume_name(project_root: Path) -> str:
    return cluster_name(project_root) + "-data"


def database_name_for_checkout(project_name: str, *, checkout: Path) -> str:
    """The database a given checkout directory owns by default.

    The main checkout gets the project name as-is, so it reads naturally and
    becomes the fork source for everything else. Other worktrees get
    `{project}_{worktree}` — unless the worktree is already named after the
    project, as `git worktree add ../myapp-feature` produces, in which case it's
    namespaced enough on its own and we don't stutter it into
    `myapp_myapp_feature`.
    """
    label = checkout_label(checkout)
    if label is None:
        # Main checkout, or no git at all — fall back to the directory itself.
        label = sanitize(checkout.name)

    if label == project_name or label.startswith(f"{project_name}_"):
        return truncate_identifier(label)
    return truncate_identifier(f"{project_name}_{label}")


def pointer_path(project_root: Path) -> Path:
    return checkout_state_path(project_root) / "database"


def read_pointer(project_root: Path) -> str | None:
    """The explicitly-assigned database for this checkout, if any.

    Presence is meaningful: it means someone ran `plain db use`. Absence means
    "derive from the directory", which is the common case.
    """
    pointer = pointer_path(project_root)
    if not pointer.exists():
        return None
    return pointer.read_text().strip() or None


def write_pointer(project_root: Path, *, db_name: str) -> None:
    pointer = pointer_path(project_root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(db_name)


def clear_pointer(project_root: Path) -> None:
    pointer_path(project_root).unlink(missing_ok=True)


def resolve_database_name(project_root: Path) -> str:
    """Pointer override, else derived from the directory."""
    if pointed := read_pointer(project_root):
        return pointed
    project_name, _ = project_identity(project_root)
    return database_name_for_checkout(project_name, checkout=project_root)
