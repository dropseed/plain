"""When plain-dev takes over Postgres, and when it stays out of the way.

The decisions here are the ones that go wrong quietly — a command running
against nobody's database, or against somebody else's — so they're pinned
even though they're internal.
"""

from __future__ import annotations

import pytest

from plain.dev.postgres.resolve import (
    CachedURL,
    cache_path,
    command_may_need_database,
    is_managed,
    read_cached_url,
    url_already_configured,
    write_cached_url,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PLAIN_POSTGRES_URL", raising=False)


# -- taking over -----------------------------------------------------------


def test_no_url_configured_by_default():
    assert not url_already_configured()


@pytest.mark.parametrize("variable", ["DATABASE_URL", "PLAIN_POSTGRES_URL"])
def test_either_env_url_counts_as_configured(monkeypatch, variable):
    monkeypatch.setenv(variable, "postgres://u@h/db")
    assert url_already_configured()


# -- the command gate ------------------------------------------------------


@pytest.mark.parametrize("command", ["docs", "code", "fix", "settings", "upgrade"])
def test_commands_that_never_need_a_database(monkeypatch, command):
    monkeypatch.setattr("sys.argv", ["plain", command])
    assert not command_may_need_database()


@pytest.mark.parametrize("command", ["dev", "shell", "test", "migrations", "db"])
def test_commands_that_do_need_a_database(monkeypatch, command):
    monkeypatch.setattr("sys.argv", ["plain", command])
    assert command_may_need_database()


def test_unknown_commands_are_assumed_to_need_a_database(monkeypatch):
    """An app's own command must not silently run without a database."""
    monkeypatch.setattr("sys.argv", ["plain", "create-user"])
    assert command_may_need_database()


def test_bare_invocation_needs_nothing(monkeypatch):
    monkeypatch.setattr("sys.argv", ["plain"])
    assert not command_may_need_database()


def test_help_needs_nothing(monkeypatch):
    monkeypatch.setattr("sys.argv", ["plain", "--help"])
    assert not command_may_need_database()


def test_only_the_top_level_command_is_considered(monkeypatch):
    """`plain run test` is not `plain test`."""
    monkeypatch.setattr("sys.argv", ["plain", "docs", "test"])
    assert not command_may_need_database()


# -- the cache -------------------------------------------------------------


def test_cache_reports_missing_when_absent(tmp_path):
    status, url = read_cached_url(tmp_path)

    assert status is CachedURL.MISSING
    assert url is None


def test_cache_reports_missing_when_blank(tmp_path):
    write_cached_url(tmp_path, "   ")

    status, _ = read_cached_url(tmp_path)
    assert status is CachedURL.MISSING


def test_cache_reports_unreachable_when_nothing_listens(tmp_path):
    # Port 1 is reserved and never has a Postgres on it.
    write_cached_url(tmp_path, "postgres://postgres:postgres@127.0.0.1:1/somedb")

    status, url = read_cached_url(tmp_path)

    assert status is CachedURL.UNREACHABLE
    assert url is not None


def test_cache_round_trip(tmp_path):
    write_cached_url(tmp_path, "postgres://u:p@127.0.0.1:5999/db")

    assert cache_path(tmp_path).read_text() == "postgres://u:p@127.0.0.1:5999/db"


# -- ownership -------------------------------------------------------------


def test_not_managed_without_a_url(tmp_path):
    assert not is_managed(tmp_path)


def test_not_managed_when_the_url_is_not_ours(tmp_path, monkeypatch):
    """A bring-your-own database must never look like one we created."""
    write_cached_url(tmp_path, "postgres://u:p@127.0.0.1:5999/ours")
    monkeypatch.setenv("DATABASE_URL", "postgres://someone@elsewhere/theirs")

    assert not is_managed(tmp_path)


def test_managed_when_the_url_matches_the_cache(tmp_path, monkeypatch):
    url = "postgres://u:p@127.0.0.1:5999/ours"
    write_cached_url(tmp_path, url)
    monkeypatch.setenv("DATABASE_URL", url)

    assert is_managed(tmp_path)


def test_not_managed_without_a_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@127.0.0.1:5999/ours")

    assert not is_managed(tmp_path)


def test_losing_a_creation_race_is_not_an_error(tmp_path, monkeypatch):
    """Several worktrees can start at once and all want the same database.

    Both see it missing, both create it, one loses. Losing means the database
    now exists, which is the whole point — so it must not crash the command.
    """
    from psycopg import errors

    from plain.dev.postgres.backends import Server
    from plain.dev.postgres.cluster import Cluster
    from plain.dev.postgres.resolve import ensure_database

    def lost_the_race(*args, **kwargs):
        raise errors.DuplicateDatabase("someone else got there first")

    def never_exists(self, name):
        return False

    def not_reached(*args, **kwargs):
        raise AssertionError("should not stamp metadata it didn't create")

    monkeypatch.setattr(Cluster, "database_exists", never_exists)
    monkeypatch.setattr(Cluster, "create_database", lost_the_race)
    monkeypatch.setattr(Cluster, "fork_database", lost_the_race)
    monkeypatch.setattr(Cluster, "set_metadata", not_reached)

    cluster = Cluster(
        Server(
            host="127.0.0.1",
            port=5999,
            user="postgres",
            password="postgres",
            backend="docker",
        )
    )

    ensure_database(cluster, tmp_path, "somedb")
