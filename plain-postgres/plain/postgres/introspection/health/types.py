from __future__ import annotations

from typing import Any, Literal, TypedDict

Source = Literal["app", "package", ""]
CheckStatus = Literal["ok", "warning", "critical", "skipped", "error"]
# "warning" — items are actionable in user's code or as an app-level action.
# "operational" — items describe DB state the user can act on via SQL but
# can't currently express in their model code (ANALYZE, VACUUM, REINDEX,
# autovacuum tuning). Rendered as context rather than alarms.
CheckTier = Literal["warning", "operational"]
PgssAvailability = Literal["usable", "not_installed", "no_permission"]


class TableOwner(TypedDict):
    package_label: str
    source: Source
    model_class: str  # e.g. "ProcessingResult" — empty if not resolvable
    model_file: str  # absolute path to the .py file declaring the model


class CheckItem(TypedDict):
    table: str
    name: str
    detail: str
    source: Source
    package: str  # package label or ""
    model_class: str  # Plain model class name; empty for non-table findings
    model_file: str  # absolute path to the model's .py file; empty when unresolved
    suggestion: str
    caveats: list[str]  # cross-check context, populated by run_all_checks


class CheckResult(TypedDict):
    name: str
    label: str
    status: CheckStatus
    summary: str
    items: list[CheckItem]
    message: str
    tier: CheckTier


class Informational(TypedDict):
    """A numeric or string fact about the database that is always shown, never
    warns. Used for context an agent may want to read but that isn't an
    actionable finding on its own (e.g. hit ratios, xid age, connection
    utilization)."""

    name: str
    label: str
    value: Any
    unit: str
    note: str
