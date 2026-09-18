"""When plain-dev takes over Postgres, and when it stays out of the way.

The decisions here are the ones that go wrong quietly — a command running
against nobody's database, or against somebody else's — so they're pinned
even though they're internal.
"""

from __future__ import annotations

import os
import sys

from helpers import sandbox
from plain.dev.postgres.identity import (
    read_pointer,
    resolve_database_name,
    write_pointer,
)
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
from plain.test import cases, patch

# -- taking over -----------------------------------------------------------


def test_no_url_configured_by_default():
    with sandbox():
        assert not url_already_configured()


@cases("DATABASE_URL", "PLAIN_POSTGRES_URL")
def test_either_env_url_counts_as_configured(variable):
    with sandbox():
        os.environ[variable] = "postgres://u@h/db"
        assert url_already_configured()


# -- the command gate ------------------------------------------------------


@cases("docs", "code", "fix", "settings", "upgrade")
def test_commands_we_never_start_a_server_for(command):
    with patch(sys, "argv", ["plain", command]):
        assert not command_may_start_server()


@cases("dev", "shell", "test", "migrations")
def test_commands_we_start_a_server_for(command):
    with patch(sys, "argv", ["plain", command]):
        assert command_may_start_server()


def test_db_does_not_start_a_server_from_setup():
    """`plain db` owns the server's lifecycle, so setup() must not touch it.

    Starting one here made `plain db server stop` stop a container it had just
    started, and let the next `plain db server list` silently start it again —
    the command undoing itself. The subcommands that need a live server open
    the cluster themselves.
    """
    with patch(sys, "argv", ["plain", "db", "server", "stop"]):
        assert not command_may_start_server()


def test_unknown_commands_are_assumed_to_want_a_server():
    """An app's own command must not silently run without a database."""
    with patch(sys, "argv", ["plain", "create-user"]):
        assert command_may_start_server()


def test_bare_invocation_starts_nothing():
    with patch(sys, "argv", ["plain"]):
        assert not command_may_start_server()


def test_help_starts_nothing():
    with patch(sys, "argv", ["plain", "--help"]):
        assert not command_may_start_server()


def test_only_the_top_level_command_is_considered():
    """`plain run test` is not `plain test`."""
    with patch(sys, "argv", ["plain", "docs", "test"]):
        assert not command_may_start_server()


# -- the cache -------------------------------------------------------------


def test_cache_reports_missing_when_absent():
    with sandbox() as box:
        status, url = read_cached_url(box.tmp_path)

        assert status is CachedURL.MISSING
        assert url is None


def test_cache_reports_missing_when_blank():
    with sandbox() as box:
        write_cached_url(box.tmp_path, url="   ")

        status, _ = read_cached_url(box.tmp_path)
        assert status is CachedURL.MISSING


def test_cache_reports_unreachable_when_nothing_listens():
    with sandbox() as box:
        # Port 1 is reserved and never has a Postgres on it.
        write_cached_url(
            box.tmp_path, url="postgres://postgres:postgres@127.0.0.1:1/somedb"
        )

        status, url = read_cached_url(box.tmp_path)

        assert status is CachedURL.UNREACHABLE
        assert url is not None


def test_cache_round_trip():
    with sandbox() as box:
        write_cached_url(box.tmp_path, url="postgres://u:p@127.0.0.1:5999/db")

        assert (
            cache_path(box.tmp_path).read_text() == "postgres://u:p@127.0.0.1:5999/db"
        )


def test_two_checkouts_never_share_pointer_or_cache():
    """Two checkouts get separate answers here — see `plain.dev.state` for why
    that's keyed by the checkout rather than stored inside it."""
    with sandbox() as box:
        main = box.tmp_path / "main"
        main.mkdir()
        worktree = box.tmp_path / "worktree"
        worktree.mkdir()

        write_pointer(main, db_name="mains_db")
        write_cached_url(main, url="postgres://u:p@127.0.0.1:5999/mains_db")

        assert read_pointer(worktree) is None
        assert read_cached_url(worktree) == (CachedURL.MISSING, None)

        # And the worktree writing doesn't disturb what main recorded.
        write_pointer(worktree, db_name="worktrees_db")
        assert read_pointer(main) == "mains_db"
        assert read_pointer(worktree) == "worktrees_db"


def test_stopped_server_still_yields_a_url_for_database_free_commands():
    """A stopped server must not break commands that never touch a database.

    `POSTGRES_URL` is a required setting, so returning nothing here left the app
    unable to configure at all — `plain docs` and `plain fix` failed with
    "Missing required setting(s): POSTGRES_URL" until you started Postgres
    again. The cached URL still names the right database while the server is
    down, and nothing connects unless the command connects.
    """
    with sandbox() as box, patch(sys, "argv", ["plain", "docs"]):
        # Port 1 is reserved, so this is cached-but-unreachable.
        write_cached_url(
            box.tmp_path, url="postgres://postgres:postgres@127.0.0.1:1/somedb"
        )

        url = ensure_postgres(box.tmp_path)

        assert url == "postgres://postgres:postgres@127.0.0.1:1/somedb"
        assert os.environ["DATABASE_URL"] == url


def test_cold_checkout_still_yields_a_url_without_starting_a_server():
    """`plain db` has to work before anything has warmed the cache.

    This was a deadlock: `db` doesn't start a server, and with no cache there was
    no URL, so `POSTGRES_URL` was missing and the CLI died before the command ran
    — including `plain db url`, which scripts use to bootstrap, and `plain db
    status`, which is the first thing anyone runs. It only worked if some *other*
    command had already populated the cache.

    Whether to start a server and which database this checkout owns are separate
    questions; only the first one is gated.
    """
    with sandbox() as box, patch(sys, "argv", ["plain", "db", "status"]):
        (box.tmp_path / "pyproject.toml").write_text("[project]\nname = 'coldapp'\n")
        assert not cache_path(box.tmp_path).exists()

        url = ensure_postgres(box.tmp_path)

        assert url is not None
        # The name is exact — it's derived, not looked up — even though no server
        # was contacted to produce it.
        assert url.endswith("/" + resolve_database_name(box.tmp_path))
        assert os.environ["DATABASE_URL"] == url
        # A URL we haven't confirmed must not become the cache.
        assert not cache_path(box.tmp_path).exists()


# -- ownership -------------------------------------------------------------


def test_not_managed_without_a_url():
    with sandbox() as box:
        assert not is_managed(box.tmp_path)


def test_not_managed_when_the_url_is_not_ours():
    """A bring-your-own database must never look like one we created."""
    with sandbox() as box:
        write_cached_url(box.tmp_path, url="postgres://u:p@127.0.0.1:5999/ours")
        os.environ["DATABASE_URL"] = "postgres://someone@elsewhere/theirs"

        assert not is_managed(box.tmp_path)


def test_managed_when_the_url_matches_the_cache():
    with sandbox() as box:
        url = "postgres://u:p@127.0.0.1:5999/ours"
        write_cached_url(box.tmp_path, url=url)
        os.environ["DATABASE_URL"] = url

        assert is_managed(box.tmp_path)


def test_not_managed_without_a_cache():
    with sandbox() as box:
        os.environ["DATABASE_URL"] = "postgres://u:p@127.0.0.1:5999/ours"

        assert not is_managed(box.tmp_path)


def test_losing_a_creation_race_is_not_an_error():
    """Several worktrees can start at once and all want the same database.

    Both see it missing, both create it, one loses. Losing means the database
    now exists, which is the whole point — so it must not crash the command.
    """
    from plain.dev.postgres.backends import Server
    from plain.dev.postgres.cluster import Cluster
    from plain.dev.postgres.resolve import ensure_database
    from psycopg import errors

    def lost_the_race(*args, **kwargs):
        raise errors.DuplicateDatabase("someone else got there first")

    def never_exists(self, name):
        return False

    def not_reached(*args, **kwargs):
        raise AssertionError("should not stamp metadata it didn't create")

    with (
        sandbox() as box,
        patch(Cluster, "database_exists", never_exists),
        patch(Cluster, "create_database", lost_the_race),
        patch(Cluster, "fork_database", lost_the_race),
        patch(Cluster, "set_metadata", not_reached),
    ):
        cluster = Cluster(
            Server(
                host="127.0.0.1",
                port=5999,
                user="postgres",
                password="postgres",
                backend="docker",
            )
        )

        ensure_database(cluster, project_root=box.tmp_path, db_name="somedb")
