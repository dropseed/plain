from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.toolbar import ToolbarItem, register_toolbar_item
from plain.utils.os import get_memory_usage, get_process_cpu_percent

from .core import Observer
from .formatting import format_bytes


def _level(value: int | float, warn: int, danger: int) -> str:
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _get_system_stats() -> dict[str, Any]:
    """Get system-level CPU and memory stats."""
    cpu_percent = get_process_cpu_percent()
    usage_bytes, limit_bytes = get_memory_usage()

    stats: dict[str, Any] = {}

    if cpu_percent is not None:
        stats["cpu_percent"] = cpu_percent
        stats["cpu_level"] = _level(cpu_percent, warn=50, danger=80)

    if limit_bytes is not None:
        mem_percent = round(usage_bytes / limit_bytes * 100)
        stats["mem_display"] = f"{mem_percent}%"
        stats["mem_title"] = (
            f"Container memory: {format_bytes(usage_bytes)} / {format_bytes(limit_bytes)}"
        )
        stats["mem_level"] = _level(mem_percent, warn=70, danger=90)
    else:
        stats["mem_display"] = format_bytes(usage_bytes, precision=0)
        stats["mem_title"] = "Server process RSS"
        stats["mem_level"] = "ok"

    return stats


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
