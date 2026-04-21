from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from ..db import use_management_connection


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
