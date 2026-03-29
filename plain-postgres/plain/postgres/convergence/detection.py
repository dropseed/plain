from __future__ import annotations

from typing import Any

from ..constraints import BaseConstraint
from ..db import get_connection
from ..indexes import Index
from ..introspection import check_model
from ..registry import models_registry
from .fixes import (
    AddConstraintFix,
    CreateIndexFix,
    DropConstraintFix,
    DropIndexFix,
    Fix,
    RebuildIndexFix,
    ValidateConstraintFix,
)


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


def detect_model_fixes(conn: Any, cursor: Any, model: Any) -> list[Fix]:
    """Detect fixes for a single model."""
    result = check_model(conn, cursor, model)
    table = result["table"]
    fixes: list[Fix] = []

    for idx in result["indexes"]:
        for issue in idx["issues"]:
            if issue["kind"] == "index_missing":
                index_obj = _find_model_index(model, idx["name"])
                if index_obj:
                    fixes.append(CreateIndexFix(table, index_obj, model))
            elif issue["kind"] == "index_invalid":
                index_obj = _find_model_index(model, idx["name"])
                if index_obj:
                    fixes.append(RebuildIndexFix(table, index_obj, model, idx["name"]))
            elif issue["kind"] == "index_extra":
                fixes.append(DropIndexFix(table, idx["name"]))

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


def _find_model_index(model: Any, name: str) -> Index | None:
    for index in model.model_options.indexes:
        if index.name == name:
            return index
    return None
