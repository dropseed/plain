from __future__ import annotations

from plain.models import db_connection
from plain.models.otel import suppress_db_tracing


def setup_database(*, verbosity: int, prefix: str = "") -> str:
    old_name = db_connection.settings_dict["NAME"]
    with suppress_db_tracing():
        db_connection.creation.create_test_db(verbosity=verbosity, prefix=prefix)
    return old_name


def teardown_database(old_name: str, verbosity: int) -> None:
    with suppress_db_tracing():
        db_connection.creation.destroy_test_db(old_name, verbosity)
