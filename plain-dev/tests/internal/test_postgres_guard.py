"""The shared-database guard forks on divergence and stays out of the way otherwise.

A planner refusal is divergence too: the code has moved past the database.
The guard must fork rather than let the error disable it.
"""

from pathlib import Path
from typing import Any, cast

import pytest
from plain.dev.postgres import guard
from plain.dev.postgres.cluster import Cluster
from plain.postgres.migrations.exceptions import ResetBoundaryError
from plain.postgres.migrations.executor import PendingMigrations


class FakeCluster:
    def __init__(self) -> None:
        self.forked: list[tuple[str, str]] = []
        self.recorded: list[str] = []

    def get_metadata(self, db_name: str) -> dict[str, Any]:
        return {"checkout": "/somebody/else"}

    def url(self, db_name: str) -> str:
        return f"postgres://fake/{db_name}"

    def database_exists(self, name: str) -> bool:
        return False

    def fork_database(self, source: str, target: str) -> str:
        self.forked.append((source, target))
        return "template"

    def record_created(self, name: str, **_: Any) -> None:
        self.recorded.append(name)


@pytest.fixture
def guarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, FakeCluster]:
    monkeypatch.setattr(guard, "checkout_id", lambda root: "/me")
    monkeypatch.setattr(guard, "project_identity", lambda root: ("proj", None))
    monkeypatch.setattr(
        guard, "database_name_for_checkout", lambda project, checkout: "proj_me"
    )
    monkeypatch.setattr(guard, "write_pointer", lambda root, db_name: None)
    return tmp_path, FakeCluster()


def as_cluster(fake: FakeCluster) -> Cluster:
    return cast(Cluster, fake)


def test_nothing_pending_keeps_the_shared_database(
    guarded: tuple[Path, FakeCluster], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cluster = guarded
    monkeypatch.setattr(
        guard, "pending_migrations", lambda url: PendingMigrations(run=0, record=0)
    )

    assert (
        guard.guard_shared_database(root, cluster=as_cluster(cluster), db_name="shared")
        == "shared"
    )
    assert cluster.forked == []


def test_a_refusal_forks_instead_of_disabling_the_guard(
    guarded: tuple[Path, FakeCluster], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cluster = guarded

    def refuse(url: str) -> PendingMigrations:
        raise ResetBoundaryError("examples", "0018_x", "2.0")

    monkeypatch.setattr(guard, "pending_migrations", refuse)

    assert (
        guard.guard_shared_database(root, cluster=as_cluster(cluster), db_name="shared")
        == "proj_me"
    )
    assert cluster.forked == [("shared", "proj_me")]
    assert cluster.recorded == ["proj_me"]
