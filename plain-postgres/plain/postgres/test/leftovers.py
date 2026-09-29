"""
What a test run may drop that it did not make, and how that is decided.

A run that was killed leaves its databases behind. Something has to remove
them, and whatever does is dropping databases it didn't create, which can't
be undone. So the rule is narrow, and it is decided in one place:
`judge_leftover`, a function of facts that touches no database.

**The record.** A run writes a record into the comment of each database it
creates: the database it was testing, its own name, where it was started,
and by which process. A database with no record is never dropped by this
module, whatever it is named. A name proves nothing: `test_shop` is the
start of `test_shop_api`'s databases too, and anyone can create a database
called `test_something`.

**Whose it is.** A database is considered only for the configured database
its record names, compared as a whole value.

**What proves its run is dead.** All of these, together:

1. The record says the run marks itself alive the way this code does (the
   advisory lock in `run_lock_key`). A record from code that does it
   another way proves nothing here.
2. Nobody holds that lock. It is asked for, and held while the database is
   dropped, so a run can't take the name in the middle.
3. The process that made it isn't running, when it was on this machine.
4. Nothing is connected to the database.

And it is dropped without `FORCE`, which fails if something connected in
the meantime. A failure there means something is using it, and it is left.

A run's lock goes with its connection to the maintenance database, and a
connection can be lost while the run lives on. That is why the lock alone
isn't the proof.
"""

import hashlib
import json
import os
import socket
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass

import psycopg
from plain.postgres.database_url import DatabaseConfig
from plain.postgres.databases import (
    connection_count,
    drop_database,
    get_database_comment,
)
from plain.postgres.sources import build_connection_params
from psycopg import errors

# The key in a database's comment that holds a run's record.
RECORD_KEY = "plain_test_run"

# How a run that wrote a record marks itself alive. Code that changes the
# lock, or what it is keyed by, changes this, and then neither version takes
# the other's databases for a dead run's.
LOCK_SCHEME = "advisory-lock-on-run-name-1"


@dataclass(frozen=True)
class RunRecord:
    """What a run writes into the comment of a database it creates."""

    database: str  # the configured database the run was testing
    run: str  # the run's shared database's name, which its lock is keyed by
    token: str  # this database's alone, so two of one name are told apart
    directory: str  # where the run was started
    host: str
    pid: int
    lock: str = LOCK_SCHEME

    def as_comment(self) -> str:
        return json.dumps({RECORD_KEY: asdict(self)})


def read_run_record(comment: str | None) -> RunRecord | None:
    """The record in a database's comment, or `None` when it holds none.

    A record that is missing a field, or has one of the wrong type, is no
    record: a database is dropped on what its record says, so one that
    can't be read in full says nothing.
    """
    if not comment:
        return None
    try:
        decoded = json.loads(comment)
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    fields = decoded.get(RECORD_KEY)
    if not isinstance(fields, dict):
        return None

    text_fields = ("database", "run", "token", "directory", "host", "lock")
    if set(fields) != {*text_fields, "pid"}:
        return None
    if not all(isinstance(fields[name], str) and fields[name] for name in text_fields):
        return None
    if type(fields["pid"]) is not int:
        return None
    return RunRecord(**fields)


def run_lock_key(run_name: str) -> int:
    """The advisory lock a run holds, from the name of its shared database."""
    digest = hashlib.sha256(f"plain.postgres.test:{run_name}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@dataclass(frozen=True)
class LeftoverFacts:
    """Everything `judge_leftover` goes by."""

    name: str
    record: RunRecord | None
    # The run's lock was asked for and got. False when someone holds it, and
    # when it wasn't asked for.
    lock_is_free: bool
    connections: int
    # Whether the process that made it is running. `None` when it was made
    # on another machine, where that can't be known.
    process_is_running: bool | None


@dataclass(frozen=True)
class LeftoverVerdict:
    drop: bool
    reason: str
    # Left, and not because its run is known to be alive or it is someone
    # else's: worth a line of output.
    in_doubt: bool = False


def judge_leftover(facts: LeftoverFacts, *, tested_database: str) -> LeftoverVerdict:
    """Whether `facts.name` is what a dead run of `tested_database` left."""
    record = facts.record
    if record is None:
        return LeftoverVerdict(
            drop=False, reason="it carries no record that a test run made it"
        )
    if record.database != tested_database:
        return LeftoverVerdict(
            drop=False, reason=f"it is a run's of {record.database!r}"
        )
    if record.lock != LOCK_SCHEME:
        return LeftoverVerdict(
            drop=False,
            reason=(
                "the run that made it marks itself alive another way"
                f" ({record.lock!r}), so whether it is alive can't be told"
            ),
            in_doubt=True,
        )
    if not facts.lock_is_free:
        return LeftoverVerdict(drop=False, reason="a run in progress holds it")
    if facts.process_is_running:
        return LeftoverVerdict(
            drop=False,
            reason=(
                f"process {record.pid}, which made it, is running,"
                " though it holds no lock"
            ),
            in_doubt=True,
        )
    if facts.connections:
        return LeftoverVerdict(
            drop=False,
            reason=(
                f"{_connections(facts.connections)} open to it, though no run holds it"
            ),
            in_doubt=True,
        )
    return LeftoverVerdict(
        drop=True,
        reason=(
            f"a test run left it (process {record.pid}, started in"
            f" {record.directory}) and is no longer alive"
        ),
    )


def _connections(count: int) -> str:
    return "1 connection is" if count == 1 else f"{count} connections are"


def process_is_running(record: RunRecord) -> bool | None:
    """Whether the process that wrote `record` is running on this machine."""
    if record.host != socket.gethostname():
        return None
    if record.pid == os.getpid():
        # This process. What carries its id and isn't held by it was made
        # by an earlier process that had the same one.
        return False
    try:
        os.kill(record.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process, and running
    return True


@contextmanager
def maintenance_connection(config: DatabaseConfig) -> Generator[psycopg.Connection]:
    """A connection to the `postgres` maintenance database, where a run's
    lock is asked for."""
    maintenance_config: DatabaseConfig = {**config, "DATABASE": "postgres"}
    with psycopg.connect(
        **build_connection_params(maintenance_config), autocommit=True
    ) as maintenance:
        yield maintenance


@contextmanager
def _run_lock(
    maintenance: psycopg.Connection, run_name: str, *, already_held: bool
) -> Generator[bool]:
    """Ask for a run's lock. Yields whether it is held here, and gives it
    back afterwards unless it was held before."""
    if already_held:
        yield True
        return

    key = run_lock_key(run_name)
    row = maintenance.execute("SELECT pg_try_advisory_lock(%s)", [key]).fetchone()
    assert row is not None
    got_it = bool(row[0])
    try:
        yield got_it
    finally:
        if got_it:
            maintenance.execute("SELECT pg_advisory_unlock(%s)", [key])


def look_at_leftover(
    maintenance: psycopg.Connection,
    config: DatabaseConfig,
    *,
    name: str,
    record: RunRecord | None,
) -> LeftoverFacts:
    """The facts about one database, read and nothing else. The run's lock
    is asked for and given straight back."""
    if record is None or record.lock != LOCK_SCHEME:
        lock_is_free = False
    else:
        with _run_lock(maintenance, record.run, already_held=False) as got_it:
            lock_is_free = got_it
    return LeftoverFacts(
        name=name,
        record=record,
        lock_is_free=lock_is_free,
        connections=connection_count(config, name=name),
        process_is_running=None if record is None else process_is_running(record),
    )


def drop_if_a_dead_runs(
    maintenance: psycopg.Connection,
    config: DatabaseConfig,
    *,
    name: str,
    record: RunRecord,
    tested_database: str,
    held_run: str = "",
) -> LeftoverVerdict:
    """Drop the database `name` if a dead run of `tested_database` left it.

    `record` is what its comment held when it was listed. Everything is
    read again here with the run's lock held, and the database is dropped
    only if it is still the one that was listed.

    `held_run` is the name of the run whose lock `maintenance` holds
    already: a run looking at what an earlier one of its own name left.
    """
    if record.lock != LOCK_SCHEME:
        facts = LeftoverFacts(
            name=name,
            record=record,
            lock_is_free=False,
            connections=0,
            process_is_running=None,
        )
        return judge_leftover(facts, tested_database=tested_database)

    with _run_lock(
        maintenance, record.run, already_held=record.run == held_run
    ) as got_it:
        now = read_run_record(get_database_comment(config, name=name))
        if now != record:
            return LeftoverVerdict(
                drop=False, reason="it isn't the database that was listed"
            )

        facts = LeftoverFacts(
            name=name,
            record=record,
            lock_is_free=got_it,
            connections=connection_count(config, name=name),
            process_is_running=process_is_running(record),
        )
        verdict = judge_leftover(facts, tested_database=tested_database)
        if not verdict.drop:
            return verdict

        try:
            # Not forced. If something connected since it was counted, this
            # fails, and the database is somebody's.
            drop_database(config, name=name, force=False)
        except errors.ObjectInUse:
            return LeftoverVerdict(
                drop=False,
                reason="something connected to it as it was being dropped",
                in_doubt=True,
            )
        return verdict


def remove_what_dead_runs_left(
    maintenance: psycopg.Connection,
    config: DatabaseConfig,
    *,
    tested_database: str,
    held_run: str,
    say: Callable[[str], None],
) -> list[str]:
    """
    Drop the databases that dead runs of `tested_database` left. The names
    of those dropped.

    Only a database whose record names `tested_database` is looked at. One
    that is left in doubt gets a line through `say`.
    """
    rows = maintenance.execute(
        "SELECT datname, shobj_description(oid, 'pg_database') "
        "FROM pg_database WHERE NOT datistemplate ORDER BY datname"
    ).fetchall()

    dropped = []
    for name, comment in rows:
        record = read_run_record(comment)
        if record is None or record.database != tested_database:
            continue
        verdict = drop_if_a_dead_runs(
            maintenance,
            config,
            name=name,
            record=record,
            tested_database=tested_database,
            held_run=held_run,
        )
        if verdict.drop:
            dropped.append(name)
        elif verdict.in_doubt:
            say(
                f"Left the test database {name!r}: {verdict.reason}."
                f" If it is debris: plain db drop {name}"
            )
    return dropped
