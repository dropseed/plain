"""
`plain db drop` and `plain db reset` drop the database that was named, and
don't throw off what is connected to it unless told to.

No server is involved: the cluster only records what it was asked to do.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import psycopg.errors
from click.testing import CliRunner, Result
from plain.dev import db
from plain.test import patch


class RecordingCluster:
    def __init__(self, *, connections: int) -> None:
        self.connections = connections
        self.dropped: list[tuple[str, bool]] = []
        self.created: list[str] = []

    def database_exists(self, name: str) -> bool:
        return True

    def connection_count(self, name: str) -> int:
        return self.connections

    def drop_database(self, name: str, *, force: bool) -> None:
        if self.connections and not force:
            raise psycopg.errors.ObjectInUse(f'database "{name}" is being accessed')
        self.dropped.append((name, force))

    def create_database(self, name: str) -> None:
        self.created.append(name)

    def record_created(self, name: str, **recorded: object) -> None:
        pass


@contextmanager
def a_project(*, connections: int = 0) -> Generator[RecordingCluster]:
    cluster = RecordingCluster(connections=connections)
    with patch(
        db,
        "_open",
        lambda: (Path("/work/plain/example"), cluster, "example", "example_mine"),
    ):
        yield cluster


def run(*arguments: str) -> Result:
    return CliRunner().invoke(db.cli, list(arguments))


def test_the_named_database_is_dropped_and_not_forced():
    with a_project() as cluster:
        result = run("drop", "example_old", "--yes")

    assert result.exit_code == 0, result.output
    assert cluster.dropped == [("example_old", False)]


def test_a_database_something_is_connected_to_is_not_dropped():
    with a_project(connections=2) as cluster:
        result = run("drop", "example_old", "--yes")

    assert result.exit_code == 1
    assert cluster.dropped == []
    assert "2 connections are open to 'example_old'" in result.output
    assert "--force" in result.output


def test_force_drops_it_with_what_is_connected():
    with a_project(connections=2) as cluster:
        result = run("drop", "example_old", "--yes", "--force")

    assert result.exit_code == 0, result.output
    assert cluster.dropped == [("example_old", True)]


def test_reset_leaves_a_database_in_use_as_it_is():
    with a_project(connections=1) as cluster:
        result = run("reset", "--yes")

    assert result.exit_code == 1
    assert cluster.dropped == []
    assert cluster.created == []
    assert "1 connection is open to 'example_mine'" in result.output


def test_reset_with_force_drops_and_recreates_it():
    with a_project(connections=1) as cluster:
        result = run("reset", "--yes", "--force")

    assert result.exit_code == 0, result.output
    assert cluster.dropped == [("example_mine", True)]
    assert cluster.created == ["example_mine"]
