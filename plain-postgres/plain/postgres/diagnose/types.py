from __future__ import annotations

from typing import TypedDict


class TableOwner(TypedDict):
    package_label: str
    source: str  # "app" | "package"


class CheckItem(TypedDict):
    table: str
    name: str
    detail: str
    source: str  # "app" | "package" | ""
    package: str  # package label or ""
    suggestion: str


class CheckResult(TypedDict):
    name: str
    label: str
    status: str  # "ok" | "warning" | "critical" | "skipped" | "error"
    summary: str
    items: list[CheckItem]
    message: str
