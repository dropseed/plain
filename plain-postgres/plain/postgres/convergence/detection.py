from __future__ import annotations

from typing import TYPE_CHECKING

from ..db import get_connection
from ..registry import models_registry
from .fixes import Fix

if TYPE_CHECKING:
    from ..base import Model
    from ..connection import DatabaseConnection
    from ..utils import CursorWrapper


def detect_fixes() -> list[Fix]:
    """Scan all models against the database and return fixes in pass order.

    Indexes are created before constraints (constraints may reference them),
    and drops happen last.
    """
    conn = get_connection()
    fixes: list[Fix] = []

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            fixes.extend(detect_model_fixes(conn, cursor, model))

    fixes.sort(key=lambda f: f.pass_order)
    return fixes


def detect_model_fixes(
    conn: DatabaseConnection, cursor: CursorWrapper, model: type[Model]
) -> list[Fix]:
    """Detect fixes for a single model."""
    from .analysis import analyze_model

    return analyze_model(conn, cursor, model).fixes
