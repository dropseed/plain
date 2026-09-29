"""
`plain db clean`, the command: what it prints, what it asks, and what it
drops once it has been answered.

No server is involved. The command is given a cluster that only records
what it was asked to drop, and facts made up for the test.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import psycopg.errors
from click.testing import CliRunner, Result
from plain.dev import db
from plain.dev.postgres.cleaning import Checkout, CleanFacts, OwnerPath
from plain.test import patch

GONE = OwnerPath(exists=False, parent_exists=False)


class RecordingCluster:
    """Drops nothing. Remembers what it was asked to."""

    def __init__(self) -> None:
        self.dropped: list[tuple[str, bool]] = []
        self.dead_runs_dropped: list[str] = []
        self.in_use: set[str] = set()

    def drop_database(self, name: str, *, force: bool) -> None:
        if name in self.in_use and not force:
            raise psycopg.errors.ObjectInUse(f'database "{name}" is being accessed')
        self.dropped.append((name, force))

    def drop_if_a_dead_runs(self, name: str) -> str | None:
        if name in self.in_use:
            return "a run in progress holds it"
        self.dead_runs_dropped.append(name)
        return None


def orphan(name: str) -> CleanFacts:
    return CleanFacts(
        name=name,
        size_bytes=7_500_000,
        recorded_checkout=f"/work/gone/{name}/example",
        owner_path=GONE,
        connections=0,
        is_test=False,
    )


def dead_runs(name: str) -> CleanFacts:
    return CleanFacts(
        name=name,
        size_bytes=7_500_000,
        recorded_checkout=None,
        owner_path=None,
        connections=0,
        is_test=True,
        run_is_dead=True,
        run_verdict="a test run left it and is no longer alive",
    )


def kept(name: str) -> CleanFacts:
    return CleanFacts(
        name=name,
        size_bytes=8_500_000,
        recorded_checkout="/work/plain/example",
        owner_path=OwnerPath(exists=True, parent_exists=True),
        connections=0,
        is_test=False,
    )


@contextmanager
def a_project_with(
    *listings: list[CleanFacts],
) -> Generator[RecordingCluster]:
    """The command's view of a project. Each time it reads the facts it gets
    the next listing, and the last one from then on."""
    cluster = RecordingCluster()
    remaining = list(listings)

    def read_facts(cluster: object, *, project_name: str) -> list[CleanFacts]:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    def checkouts(project_root: Path) -> tuple[list[Checkout], bool]:
        here = Checkout(
            path="/work/plain/example",
            worktree="/work/plain",
            exists=True,
            database="example",
        )
        return [here], True

    with (
        patch(
            db,
            "_open",
            lambda: (Path("/work/plain/example"), cluster, "example", "example"),
        ),
        patch(db, "read_clean_facts", read_facts),
        patch(db, "project_checkouts", checkouts),
    ):
        yield cluster


def clean(*arguments: str, answer: str = "") -> Result:
    return CliRunner().invoke(db.cli, ["clean", *arguments], input=answer)


def test_a_dry_run_lists_everything_and_drops_nothing():
    listing = [kept("example"), orphan("example_typed_writes"), dead_runs("test_x_r1")]
    with a_project_with(listing) as cluster:
        result = clean("--dry-run")

    assert result.exit_code == 0, result.output
    assert "Would drop 2" in result.output
    assert "example_typed_writes" in result.output
    assert "/work/gone/example_typed_writes/example" in result.output
    assert "its checkout is gone" in result.output
    assert "a test run left it and is no longer alive" in result.output
    assert "Leaving 1" in result.output
    assert "the project's main database" in result.output
    assert "Drop the" not in result.output
    assert cluster.dropped == []
    assert cluster.dead_runs_dropped == []


def test_the_listing_is_printed_before_the_question():
    with a_project_with([kept("example"), orphan("example_typed_writes")]):
        result = clean(answer="n\n")

    listed = result.output.index("example_typed_writes")
    asked = result.output.index('Drop the 1 listed under "Would drop"?')
    assert listed < asked
    assert "Leaving 1" in result.output[:asked]


def test_nothing_is_dropped_when_the_answer_is_no():
    with a_project_with([orphan("example_typed_writes")]) as cluster:
        result = clean(answer="n\n")

    assert result.exit_code == 0, result.output
    assert cluster.dropped == []


def test_nothing_is_dropped_when_nobody_answers():
    """Run by something that can't answer: a script, an agent."""
    with a_project_with([orphan("example_typed_writes")]) as cluster:
        result = clean(answer="")

    assert result.exit_code != 0
    assert cluster.dropped == []


def test_there_is_no_flag_that_skips_the_question():
    for flag in ("--yes", "-y"):
        with a_project_with([orphan("example_typed_writes")]) as cluster:
            result = clean(flag)

        assert result.exit_code == 2, result.output
        assert "No such option" in result.output
        assert cluster.dropped == []


def test_what_was_listed_is_dropped_on_a_yes_and_never_forced():
    listing = [kept("example"), orphan("example_typed_writes"), dead_runs("test_x_r1")]
    with a_project_with(listing) as cluster:
        result = clean(answer="y\n")

    assert result.exit_code == 0, result.output
    assert cluster.dropped == [("example_typed_writes", False)]
    assert cluster.dead_runs_dropped == ["test_x_r1"]
    assert "Dropped 2" in result.output


def test_a_database_that_stopped_qualifying_while_the_question_waited_is_left():
    listed = [orphan("example_typed_writes"), orphan("example_typed_reads")]
    by_the_answer = [kept("example_typed_writes"), orphan("example_typed_reads")]
    with a_project_with(listed, by_the_answer) as cluster:
        result = clean(answer="y\n")

    assert cluster.dropped == [("example_typed_reads", False)]
    assert "Left example_typed_writes: it no longer qualifies." in result.output
    assert "Dropped 1" in result.output


def test_a_database_that_started_qualifying_while_the_question_waited_is_left():
    """It wasn't in the listing the answer was given to."""
    listed = [orphan("example_typed_writes"), kept("example_typed_reads")]
    by_the_answer = [orphan("example_typed_writes"), orphan("example_typed_reads")]
    with a_project_with(listed, by_the_answer) as cluster:
        clean(answer="y\n")

    assert cluster.dropped == [("example_typed_writes", False)]


def test_a_database_something_connected_to_is_left_and_the_rest_are_dropped():
    listing = [orphan("example_typed_writes"), orphan("example_typed_reads")]
    with a_project_with(listing) as cluster:
        cluster.in_use.add("example_typed_writes")
        result = clean(answer="y\n")

    assert cluster.dropped == [("example_typed_reads", False)]
    assert (
        "Left example_typed_writes: something connected to it as it was being dropped."
        in result.output
    )
    assert "Dropped 1" in result.output


def test_a_test_database_whose_run_turned_out_alive_is_left():
    with a_project_with([dead_runs("test_x_r1")]) as cluster:
        cluster.in_use.add("test_x_r1")
        result = clean(answer="y\n")

    assert cluster.dead_runs_dropped == []
    assert "Left test_x_r1: a run in progress holds it." in result.output
    assert "Dropped 0" in result.output


def test_with_nothing_to_drop_it_says_so_and_doesnt_ask():
    with a_project_with([kept("example")]) as cluster:
        result = clean()

    assert result.exit_code == 0, result.output
    assert "Nothing to drop." in result.output
    assert "Leaving 1" in result.output
    assert "Drop the" not in result.output
    assert cluster.dropped == []
