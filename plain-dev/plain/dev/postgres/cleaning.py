"""What `plain db clean` may drop, and why it leaves the rest.

Dropping a database can't be undone, and `plain db clean` drops databases
nobody named. So what it may drop is decided in one function of facts,
`plan_clean`, which touches no database and no disk, and everything it is
given is listed with the reason: what would be dropped, and what is left.

**A development database** is dropped only when all of this is so:

- It isn't the project's main database, or this checkout's.
- No checkout of the project is configured to use it. This goes by what each
  checkout uses now, not by who the database's metadata says made it: a
  worktree that was moved, or pointed at it with `plain db use`, uses it
  whatever the metadata says.
- Its metadata names the checkout that made it, and that checkout is gone.
- Nothing is connected to it.

**When a checkout is gone.** Its directory is missing, and:

- in a git repository, git lists no worktree that holds it. A worktree git
  still lists whose directory is missing may be on a volume that isn't
  mounted, so its database is left until `git worktree prune` says
  otherwise.
- outside git, the directory that held it is still there. When that is
  missing too, nothing can be told from the path.

**A test database** is dropped only when it carries the record of the run
that made it and that run is proved dead. **A template**, which a
database's test runs clone, is dropped only when its record says it is of
no use now: the schema of this checkout's database has changed since it
was built, the database it was built for is gone from the server, or the
run building it died before it was done. `plain.postgres.test.leftovers`
has both rules, and this module only reports its verdicts.

Outside a git repository the only checkout known is the one the command
runs from, so "no checkout is configured to use it" can only be checked for
that one.
"""

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from .identity import _run_git, resolve_database_name

if TYPE_CHECKING:
    from plain.postgres.test.leftovers import LeftoverVerdict

    from .cluster import Cluster, DevDatabase


@dataclass(frozen=True)
class Checkout:
    """A checkout of the project: a git worktree's copy of the project root."""

    path: str
    # The worktree it is in, as git lists it. Outside git, the same as `path`.
    worktree: str
    # Its directory is there. A worktree git lists can be missing: removed
    # by hand and not pruned, or on a volume that isn't mounted.
    exists: bool
    # The database it is configured to use. `None` when it is missing.
    database: str | None


@dataclass(frozen=True)
class OwnerPath:
    """What is on disk where a database's metadata says its checkout was."""

    exists: bool
    parent_exists: bool


@dataclass(frozen=True)
class CleanFacts:
    """Everything `plan_clean` goes by, about one database."""

    name: str
    size_bytes: int
    # The checkout its metadata names, and what is there now.
    recorded_checkout: str | None
    owner_path: OwnerPath | None
    connections: int
    is_test: bool
    # For a test database: whether its run is proved dead, and the reason.
    # Both from `plain.postgres.test.leftovers.judge_leftover`. For a
    # template (a test database with `is_template` too): whether it is of
    # no use now, and why, from `judge_template`.
    run_is_dead: bool = False
    run_verdict: str = ""
    is_template: bool = False
    # For a template: whether the database it was built for is gone from
    # the server. Dropping it then needs the same fact.
    tested_database_is_gone: bool = False


@dataclass(frozen=True)
class CleanItem:
    name: str
    size_bytes: int
    owner: str
    reason: str
    is_test: bool
    is_template: bool = False
    tested_database_is_gone: bool = False


@dataclass(frozen=True)
class CleanPlan:
    drop: tuple[CleanItem, ...]
    leave: tuple[CleanItem, ...]


def plan_clean(
    databases: list[CleanFacts],
    *,
    project_main: str,
    current: str,
    checkouts: list[Checkout],
    in_git: bool,
) -> CleanPlan:
    """Sort every database into what to drop and what to leave, with why."""
    drop = []
    leave = []
    for facts in databases:
        dropping, reason = _judge(
            facts,
            project_main=project_main,
            current=current,
            checkouts=checkouts,
            in_git=in_git,
        )
        item = CleanItem(
            name=facts.name,
            size_bytes=facts.size_bytes,
            owner=_owner(facts),
            reason=reason,
            is_test=facts.is_test,
            is_template=facts.is_template,
            tested_database_is_gone=facts.tested_database_is_gone,
        )
        (drop if dropping else leave).append(item)
    return CleanPlan(drop=tuple(drop), leave=tuple(leave))


def _owner(facts: CleanFacts) -> str:
    if facts.is_template:
        return "(test template)"
    if facts.is_test:
        return "(test database)"
    return facts.recorded_checkout or "(no recorded owner)"


def _judge(
    facts: CleanFacts,
    *,
    project_main: str,
    current: str,
    checkouts: list[Checkout],
    in_git: bool,
) -> tuple[bool, str]:
    if facts.name == project_main:
        return False, "the project's main database, which every checkout forks from"
    if facts.name == current:
        return False, "this checkout's database"

    for checkout in checkouts:
        if checkout.database == facts.name:
            return False, f"the checkout at {checkout.path} is configured to use it"

    if facts.is_test:
        return facts.run_is_dead, facts.run_verdict

    if not facts.recorded_checkout or facts.owner_path is None:
        return False, "no record of which checkout made it"
    if facts.owner_path.exists:
        return False, "its checkout is there"

    if in_git:
        holder = _worktree_holding(facts.recorded_checkout, checkouts=checkouts)
        if holder is not None:
            return False, (
                f"git lists a worktree at {holder.worktree}, though its directory"
                " is missing (a volume that isn't mounted, or a worktree"
                " removed by hand: `git worktree prune` settles it)"
            )
    elif not facts.owner_path.parent_exists:
        return False, (
            "its checkout's directory is missing and so is the directory"
            " that held it, so whether the checkout is gone can't be told"
        )

    if facts.connections:
        count = facts.connections
        open_to_it = "1 connection is" if count == 1 else f"{count} connections are"
        return False, f"{open_to_it} open to it, though its checkout is gone"

    return True, "its checkout is gone"


def _worktree_holding(path: str, *, checkouts: list[Checkout]) -> Checkout | None:
    """The checkout whose worktree git lists and `path` is in, if its
    directory is missing."""
    for checkout in checkouts:
        if checkout.exists:
            continue
        if PurePath(path).is_relative_to(PurePath(checkout.worktree)):
            return checkout
    return None


# ---------------------------------------------------------------------------
# Reading the facts
# ---------------------------------------------------------------------------


def look_at_owner_path(recorded_checkout: str | None) -> OwnerPath | None:
    if not recorded_checkout:
        return None
    path = Path(recorded_checkout)
    return OwnerPath(exists=path.exists(), parent_exists=path.parent.exists())


def project_checkouts(project_root: Path) -> tuple[list[Checkout], bool]:
    """
    The project's checkouts, and whether the project is in a git
    repository.

    In git, the repository's worktrees are the checkouts: for each one git
    lists, the directory in it where this project's root is. Outside git,
    the only checkout known is `project_root`.
    """
    toplevel = _run_git(["rev-parse", "--show-toplevel"], project_root)
    listing = _run_git(["worktree", "list", "--porcelain"], project_root)
    if toplevel is None or listing is None:
        return [_checkout_at(project_root, worktree=project_root)], False

    # Where the project's root is inside a worktree: `example`, or nowhere
    # deeper than the worktree itself.
    inside = project_root.resolve().relative_to(Path(toplevel).resolve())

    checkouts = []
    for line in listing.splitlines():
        if line.startswith("worktree "):
            worktree = Path(line.removeprefix("worktree "))
            checkouts.append(_checkout_at(worktree / inside, worktree=worktree))
    return checkouts, True


def _checkout_at(root: Path, *, worktree: Path) -> Checkout:
    # Resolved the way a checkout's path is when it is recorded, so the two
    # compare. For a missing directory that settles what of it is there.
    if not root.is_dir():
        return Checkout(
            path=str(root.resolve()),
            worktree=str(worktree.resolve()),
            exists=False,
            database=None,
        )
    return Checkout(
        path=str(root.resolve()),
        worktree=str(worktree.resolve()),
        exists=True,
        database=resolve_database_name(root.resolve()),
    )


def read_clean_facts(
    cluster: Cluster,
    *,
    project_name: str,
    current: str,
    current_schema: str | None,
) -> list[CleanFacts]:
    """The facts about every database of the project. Reads, and changes
    nothing: a test database's run lock is asked for and given straight back.

    `current_schema` is the digest of the schema this checkout's database,
    `current`, builds its test databases with now, which is what tells its
    template from a stale one. `None` when it couldn't be worked out, and
    then the template is left.
    """
    from plain.postgres.test.leftovers import (
        judge_leftover,
        judge_template,
        look_at_leftover,
        look_at_template,
        maintenance_connection,
    )

    databases = cluster.list_databases(project_name)
    names = {database.name for database in databases}
    facts = []
    with maintenance_connection(cluster.config) as maintenance:
        for database in databases:
            if database.template_record is not None:
                template = database.template_record
                gone = template.database not in names
                facts.append(
                    _test_database_facts(
                        database,
                        verdict=judge_template(
                            look_at_template(
                                maintenance,
                                cluster.config,
                                name=database.name,
                                record=template,
                            ),
                            current_schema=current_schema
                            if template.database == current
                            else None,
                            tested_database_is_gone=gone,
                        ),
                        is_template=True,
                        tested_database_is_gone=gone,
                    )
                )
            elif database.is_test:
                facts.append(
                    _test_database_facts(
                        database,
                        verdict=judge_leftover(
                            look_at_leftover(
                                maintenance,
                                cluster.config,
                                name=database.name,
                                record=database.run_record,
                            ),
                            tested_database=_tested_database(database),
                        ),
                    )
                )
            else:
                facts.append(
                    CleanFacts(
                        name=database.name,
                        size_bytes=database.size_bytes,
                        recorded_checkout=database.checkout,
                        owner_path=look_at_owner_path(database.checkout),
                        connections=cluster.connection_count(database.name),
                        is_test=False,
                    )
                )
    return facts


def _tested_database(database: DevDatabase) -> str:
    return database.run_record.database if database.run_record else ""


def _test_database_facts(
    database: DevDatabase,
    *,
    verdict: LeftoverVerdict,
    is_template: bool = False,
    tested_database_is_gone: bool = False,
) -> CleanFacts:
    reason = verdict.reason
    if database.run_record is None and database.template_record is None:
        reason += f" (if it is debris: plain db drop {database.name})"
    return CleanFacts(
        name=database.name,
        size_bytes=database.size_bytes,
        recorded_checkout=None,
        owner_path=None,
        connections=0,
        is_test=True,
        run_is_dead=verdict.drop,
        run_verdict=reason,
        is_template=is_template,
        tested_database_is_gone=tested_database_is_gone,
    )
