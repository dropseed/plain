"""Shared helpers for the plain-postgres tests."""

import atexit
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from plain.postgres.database_url import (
    DatabaseConfig,
    parse_database_url,
    replace_database_name,
)
from plain.postgres.db import _db_conn
from plain.postgres.test import CapturedQueries


@contextmanager
def clean_connection() -> Generator[None]:
    """Start the connection ContextVar empty and clean up any connection
    created inside the block, restoring the previous connection on exit."""
    token = _db_conn.set(None)
    try:
        yield
    finally:
        conn = _db_conn.get()
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        _db_conn.reset(token)


def executed_sql(queries: CapturedQueries) -> str:
    """Join the statements recorded by ``capture_queries`` into one string.

        with capture_queries() as queries:
            Model.query.filter(...).delete()
        assert "FOR UPDATE" in executed_sql(queries)

    Transaction control is left out -- savepoints included, which the test
    lifecycle wraps every test in -- so a block inside ``atomic()`` reads the
    same as one that wasn't, and what comes back is replayable SQL.
    """
    control = ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")
    return " ".join(
        query.sql_with_params
        for query in queries
        if not query.sql_with_params.startswith(control)
    )


# ---------------------------------------------------------------------------
# A run of the tests, in a process of its own
# ---------------------------------------------------------------------------

_SCRATCH_APP = {
    "app/settings.py": (
        'SECRET_KEY = "test"\n'
        'URLS_ROUTER = "app.urls.AppRouter"\n'
        'INSTALLED_PACKAGES = ["plain.postgres"]\n'
    ),
    "app/urls.py": (
        "from plain.urls import Router\n"
        "\n"
        "\n"
        "class AppRouter(Router):\n"
        '    namespace = ""\n'
        "    urls = ()\n"
    ),
    # Python imports `sitecustomize` when it starts, so this records every
    # connection the run makes, from the first.
    "site/sitecustomize.py": (
        "import os\n"
        "\n"
        "import psycopg\n"
        "\n"
        "_connect = psycopg.Connection.connect.__func__\n"
        "\n"
        "\n"
        'def _recording_connect(cls, conninfo="", **kwargs):\n'
        '    with open(os.environ["CONNECTIONS_RECORD"], "a") as record:\n'
        "        record.write(f\"{kwargs.get('dbname')}\\n\")\n"
        "    return _connect(cls, conninfo, **kwargs)\n"
        "\n"
        "\n"
        "psycopg.Connection.connect = classmethod(_recording_connect)\n"
        "psycopg.connect = psycopg.Connection.connect\n"
    ),
}


@dataclass
class ScratchApp:
    """
    An app on disk with `plain.postgres` installed and nothing else, and a
    configured database of its own name that doesn't exist. No run of the
    tests has a reason to connect to the configured database, so it not
    existing is no obstacle, and any connection to it would fail loudly.
    """

    root: Path
    configured_url: str
    configured_name: str

    @property
    def config(self) -> DatabaseConfig:
        return parse_database_url(self.configured_url)

    @property
    def connections_record(self) -> Path:
        return self.root / "connections.txt"

    def connected_to(self) -> list[str]:
        """The database of every connection the runs here made, in order."""
        if not self.connections_record.exists():
            return []
        return self.connections_record.read_text().split()

    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "PLAIN_POSTGRES_URL": self.configured_url,
            "CONNECTIONS_RECORD": str(self.connections_record),
            "PYTHONPATH": str(self.root / "site"),
        }

    def start_run(
        self, *, environment: dict[str, str] | None = None
    ) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "plain.test"],
            cwd=self.root,
            env={**self.environment(), **(environment or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
        )

    def run(self, *, environment: dict[str, str] | None = None) -> tuple[int, str]:
        """Run the tests here. The exit code, and everything printed."""
        process = self.start_run(environment=environment)
        output, _ = process.communicate(timeout=120)
        return process.returncode, output


def make_scratch_app(test_files: dict[str, str]) -> ScratchApp:
    root = Path(tempfile.mkdtemp(prefix="plain-postgres-scratch-")).resolve()
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    for name, source in {**_SCRATCH_APP, **test_files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)

    # The URL as configured for this run of the tests. `settings.POSTGRES_URL`
    # is the test database while tests run; the environment is as it was.
    url_of_this_run = os.environ["PLAIN_POSTGRES_URL"]
    name_of_this_run = parse_database_url(url_of_this_run)["DATABASE"]
    configured_name = f"{name_of_this_run}_s{secrets.token_hex(3)}"
    return ScratchApp(
        root=root,
        configured_url=replace_database_name(url_of_this_run, configured_name),
        configured_name=configured_name,
    )
