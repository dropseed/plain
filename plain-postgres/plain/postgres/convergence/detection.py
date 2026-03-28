from __future__ import annotations

from typing import Any

from ..constraints import BaseConstraint
from ..db import get_connection
from ..introspection import check_model
from ..registry import models_registry
from .fixes import AddConstraintFix, ColumnTypeFix, DropConstraintFix, Fix


def detect_fixes() -> list[Fix]:
    """Scan all models against the database and return fixes for mismatches."""
    conn = get_connection()
    fixes: list[Fix] = []

    with conn.cursor() as cursor:
        for model in models_registry.get_models():
            fixes.extend(detect_model_fixes(conn, cursor, model))

    return fixes


def detect_model_fixes(conn: Any, cursor: Any, model: Any) -> list[Fix]:
    """Detect fixes for a single model."""
    result = check_model(conn, cursor, model)
    table = result["table"]
    fixes: list[Fix] = []

    for col in result["columns"]:
        for issue in col["issues"]:
            if issue["kind"] == "type_mismatch":
                expected = issue["detail"].split("expected ")[1].split(",")[0]
                actual = issue["detail"].split("actual ")[1]
                if _is_safe_type_fix(actual, expected):
                    fixes.append(ColumnTypeFix(table, col["name"], actual, expected))

    for con in result["constraints"]:
        for issue in con["issues"]:
            if issue["kind"] == "constraint_missing" and con["type"] in (
                "check",
                "unique",
            ):
                constraint_obj = _find_model_constraint(model, con["name"])
                if constraint_obj:
                    fixes.append(AddConstraintFix(table, constraint_obj, model))
            elif issue["kind"] == "constraint_extra" and con["type"] in (
                "check",
                "unique",
            ):
                fixes.append(DropConstraintFix(table, con["name"]))

    return fixes


def _find_model_constraint(model: Any, name: str) -> BaseConstraint | None:
    for constraint in model.model_options.constraints:
        if constraint.name == name:
            return constraint
    return None


def _is_safe_type_fix(actual: str, expected: str) -> bool:
    """Return True if converting actual → expected is safe (no data loss, no rewrite)."""
    if actual.startswith("character varying") and expected == "text":
        return True
    return False
