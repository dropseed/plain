from __future__ import annotations

from plain.postgres.db import get_connection
from plain.postgres.otel import suppress_db_tracing


def setup_database(*, verbosity: int, prefix: str = "") -> str:
    conn = get_connection()
    old_name = conn.settings_dict["DATABASE"]
    assert old_name is not None, "DATABASE setting must be set before creating test db"
    with suppress_db_tracing():
        conn.create_test_db(verbosity=verbosity, prefix=prefix)
    return old_name


def teardown_database(old_name: str, verbosity: int) -> None:
    with suppress_db_tracing():
        get_connection().destroy_test_db(old_name, verbosity)
