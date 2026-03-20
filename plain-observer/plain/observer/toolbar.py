from __future__ import annotations

import os
from functools import cached_property
from typing import Any

import psutil

from plain.toolbar import ToolbarItem, register_toolbar_item
from plain.utils.os import get_cpu_count

from .core import Observer

_cpu_count = get_cpu_count()


def _level(value: int | float, warn: int, danger: int) -> str:
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _get_system_stats() -> dict[str, Any]:
    """Get system-level CPU and memory stats."""
    load_1, _, _ = os.getloadavg()
    cpu_percent = min(round(load_1 / _cpu_count * 100), 100)
    mem_percent = round(psutil.virtual_memory().percent)

    return {
        "cpu_percent": cpu_percent,
        "cpu_level": _level(cpu_percent, warn=50, danger=80),
        "mem_percent": mem_percent,
        "mem_level": _level(mem_percent, warn=70, danger=90),
    }


def _get_trace_stats(observer: Observer) -> dict[str, Any] | None:
    """Get trace-level stats with levels and display values."""
    stats = observer.get_current_trace_stats()
    if stats is None:
        return None

    query_count = stats["query_count"]
    duplicate_count = stats["duplicate_count"]
    duration_ms = stats["duration_ms"]

    # Any duplicate queries promote to at least "warn" (N+1 indicator)
    query_level = _level(query_count, warn=10, danger=30)
    if duplicate_count > 0 and query_level == "ok":
        query_level = "warn"

    # Format duration for display
    if duration_ms is not None:
        duration_ms_rounded = round(duration_ms)
        if duration_ms >= 1000:
            duration_display = f"{duration_ms / 1000:.1f}s"
        else:
            duration_display = f"{duration_ms_rounded}ms"
        duration_level = _level(duration_ms_rounded, warn=200, danger=1000)
    else:
        duration_display = None
        duration_level = "ok"

    return {
        "query_count": query_count,
        "duplicate_count": duplicate_count,
        "query_level": query_level,
        "duration_display": duration_display,
        "duration_level": duration_level,
    }


@register_toolbar_item
class ObserverToolbarItem(ToolbarItem):
    name = "Observer"
    panel_template_name = "toolbar/observer.html"
    button_template_name = "toolbar/observer_button.html"

    @cached_property
    def observer(self) -> Observer:
        """Get the Observer instance for this request."""
        return Observer.from_request(self.request)

    @cached_property
    def _context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["observer"] = self.observer
        context["system_stats"] = _get_system_stats()
        context["trace_stats"] = _get_trace_stats(self.observer)
        return context

    def get_template_context(self) -> dict[str, Any]:
        return self._context
