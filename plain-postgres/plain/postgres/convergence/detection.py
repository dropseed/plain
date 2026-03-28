from __future__ import annotations

from typing import Any

from ..constraints import BaseConstraint
from ..db import get_connection
from ..introspection import check_model
from ..registry import models_registry
from .fixes import (
    AddConstraintFix,
    DropConstraintFix,
    Fix,
    ValidateConstraintFix,
)


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

    for con in result["constraints"]:
        for issue in con["issues"]:
            if issue["kind"] == "constraint_missing" and con["type"] in (
                "check",
                "unique",
            ):
                constraint_obj = _find_model_constraint(model, con["name"])
                if constraint_obj:
                    fixes.append(AddConstraintFix(table, constraint_obj, model))
            elif issue["kind"] == "constraint_not_valid" and con["type"] in (
                "check",
                "unique",
            ):
                fixes.append(ValidateConstraintFix(table, con["name"]))
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
