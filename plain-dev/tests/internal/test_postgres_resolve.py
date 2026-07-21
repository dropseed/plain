"""When plain-dev takes over Postgres, and when it stays out of the way.

The decisions here are the ones that go wrong quietly — a command running
against nobody's database, or against somebody else's — so they're pinned
even though they're internal.
"""

from __future__ import annotations

import os

import pytest

from plain.dev.postgres.identity import resolve_database_name
from plain.dev.postgres.resolve import (
    CachedURL,
    cache_path,
    command_may_start_server,
    ensure_postgres,
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
def test_commands_we_never_start_a_server_for(monkeypatch, command):
    monkeypatch.setattr("sys.argv", ["plain", command])
    assert not command_may_start_server()


@pytest.mark.parametrize("command", ["dev", "shell", "test", "migrations"])
def test_commands_we_start_a_server_for(monkeypatch, command):
    monkeypatch.setattr("sys.argv", ["plain", command])
    assert command_may_start_server()


def test_db_does_not_start_a_server_from_setup(monkeypatch):
    """`plain db` owns the server's lifecycle, so setup() must not touch it.

    Starting one here made `plain db server stop` stop a container it had just
    started, and let the next `plain db server list` silently start it again —
    the command undoing itself. The subcommands that need a live server open
    the cluster themselves.
    """
    monkeypatch.setattr("sys.argv", ["plain", "db", "server", "stop"])
    assert not command_may_start_server()


def test_unknown_commands_are_assumed_to_want_a_server(monkeypatch):
    """An app's own command must not silently run without a database."""
    monkeypatch.setattr("sys.argv", ["plain", "create-user"])
    assert command_may_start_server()


def test_bare_invocation_starts_nothing(monkeypatch):
    monkeypatch.setattr("sys.argv", ["plain"])
    assert not command_may_start_server()


def test_help_starts_nothing(monkeypatch):
    monkeypatch.setattr("sys.argv", ["plain", "--help"])
    assert not command_may_start_server()


def test_only_the_top_level_command_is_considered(monkeypatch):
    """`plain run test` is not `plain test`."""
    monkeypatch.setattr("sys.argv", ["plain", "docs", "test"])
    assert not command_may_start_server()


# -- the cache -------------------------------------------------------------


def test_cache_reports_missing_when_absent(tmp_path):
    status, url = read_cached_url(tmp_path)

    assert status is CachedURL.MISSING
    assert url is None


def test_cache_reports_missing_when_blank(tmp_path):
    write_cached_url(tmp_path, url="   ")

    status, _ = read_cached_url(tmp_path)
    assert status is CachedURL.MISSING


def test_cache_reports_unreachable_when_nothing_listens(tmp_path):
    # Port 1 is reserved and never has a Postgres on it.
    write_cached_url(tmp_path, url="postgres://postgres:postgres@127.0.0.1:1/somedb")

    status, url = read_cached_url(tmp_path)

    assert status is CachedURL.UNREACHABLE
    assert url is not None


def test_cache_round_trip(tmp_path):
    write_cached_url(tmp_path, url="postgres://u:p@127.0.0.1:5999/db")

    assert cache_path(tmp_path).read_text() == "postgres://u:p@127.0.0.1:5999/db"


def test_stopped_server_still_yields_a_url_for_database_free_commands(
    tmp_path, monkeypatch
):
    """A stopped server must not break commands that never touch a database.

    `POSTGRES_URL` is a required setting, so returning nothing here left the app
    unable to configure at all — `plain docs` and `plain fix` failed with
    "Missing required setting(s): POSTGRES_URL" until you started Postgres
    again. The cached URL still names the right database while the server is
    down, and nothing connects unless the command connects.
    """
    monkeypatch.setattr("sys.argv", ["plain", "docs"])
    # Port 1 is reserved, so this is cached-but-unreachable.
    write_cached_url(tmp_path, url="postgres://postgres:postgres@127.0.0.1:1/somedb")

    url = ensure_postgres(tmp_path)

    assert url == "postgres://postgres:postgres@127.0.0.1:1/somedb"
    assert os.environ["DATABASE_URL"] == url


def test_cold_checkout_still_yields_a_url_without_starting_a_server(
    tmp_path, monkeypatch
):
    """`plain db` has to work before anything has warmed the cache.

    This was a deadlock: `db` doesn't start a server, and with no cache there was
    no URL, so `POSTGRES_URL` was missing and the CLI died before the command ran
    — including `plain db url`, which scripts use to bootstrap, and `plain db
    status`, which is the first thing anyone runs. It only worked if some *other*
    command had already populated the cache.

    Whether to start a server and which database this checkout owns are separate
    questions; only the first one is gated.
    """
    monkeypatch.setattr("sys.argv", ["plain", "db", "status"])
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'coldapp'\n")
    assert not cache_path(tmp_path).exists()

    url = ensure_postgres(tmp_path)

    assert url is not None
    # The name is exact — it's derived, not looked up — even though no server
    # was contacted to produce it.
    assert url.endswith("/" + resolve_database_name(tmp_path))
    assert os.environ["DATABASE_URL"] == url
    # A URL we haven't confirmed must not become the cache.
    assert not cache_path(tmp_path).exists()


# -- ownership -------------------------------------------------------------


def test_not_managed_without_a_url(tmp_path):
    assert not is_managed(tmp_path)


def test_not_managed_when_the_url_is_not_ours(tmp_path, monkeypatch):
    """A bring-your-own database must never look like one we created."""
    write_cached_url(tmp_path, url="postgres://u:p@127.0.0.1:5999/ours")
    monkeypatch.setenv("DATABASE_URL", "postgres://someone@elsewhere/theirs")

    assert not is_managed(tmp_path)


def test_managed_when_the_url_matches_the_cache(tmp_path, monkeypatch):
    url = "postgres://u:p@127.0.0.1:5999/ours"
    write_cached_url(tmp_path, url=url)
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

    ensure_database(cluster, project_root=tmp_path, db_name="somedb")
