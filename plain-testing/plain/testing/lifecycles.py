"""
Lifecycle discovery.

Packages register a TestLifecycle subclass under the `plain.testing` entry
point group; the runner discovers and drives them. This entry point group is
the entire extension API.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from plain.test.lifecycle import TestLifecycle

__all__ = ["load_lifecycles"]


def load_lifecycles() -> list[TestLifecycle]:
    lifecycles = []
    for entry_point in sorted(
        entry_points(group="plain.testing"), key=lambda e: e.name
    ):
        lifecycle_class = entry_point.load()
        lifecycles.append(lifecycle_class())
    return lifecycles
