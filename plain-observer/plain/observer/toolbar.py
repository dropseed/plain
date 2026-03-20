from __future__ import annotations

import os
from functools import cached_property
from typing import Any

import psutil

from plain.toolbar import ToolbarItem, register_toolbar_item
from plain.utils.os import get_cpu_count

from .core import Observer

_cpu_count = get_cpu_count()


def _level(value: int, warn: int, danger: int) -> str:
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

    cpu_level = _level(cpu_percent, warn=50, danger=80)
    mem_level = _level(mem_percent, warn=70, danger=90)

    # Worst level for the aggregate dot
    if "danger" in (cpu_level, mem_level):
        level = "danger"
    elif "warn" in (cpu_level, mem_level):
        level = "warn"
    else:
        level = "ok"

    return {
        "cpu_percent": cpu_percent,
        "cpu_level": cpu_level,
        "mem_percent": mem_percent,
        "mem_level": mem_level,
        "level": level,
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
        return context

    def get_template_context(self) -> dict[str, Any]:
        return self._context
