from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import click

from ..db import use_management_connection
from ..schema_lock import SchemaLockLost, SchemaLockTimeout, schema_lock


@contextmanager
def cli_schema_lock() -> Iterator[Callable[[], None]]:
    """`schema_lock()` for CLI commands: a timeout or lost lock surfaces as a
    clean one-line error instead of a traceback burying it. Yields the lock's
    verify callable for multi-phase commands to check between phases."""
    try:
        with schema_lock() as verify:
            yield verify
    except (SchemaLockTimeout, SchemaLockLost) as e:
        raise click.ClickException(str(e)) from e


def database_management_command[F: Callable[..., Any]](f: F) -> F:
    """Run a click command's body through `use_management_connection()`.

    Apply to CLI commands that perform schema changes, migrations, or other
    database management operations. Inside the command, `get_connection()`
    returns a connection opened against `POSTGRES_MANAGEMENT_URL` (falling
    back to `POSTGRES_URL` when unset).
    """

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with use_management_connection():
            return f(*args, **kwargs)

    return wrapper  # ty: ignore[invalid-return-type]
