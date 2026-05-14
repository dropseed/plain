"""Defaults for optional package-helper globals.

These are minimal stand-ins that templates can rely on when the underlying
package isn't installed. The actual implementations live in the home
packages (`plain.tailwind`, `plain.htmx`, `plain.pageviews`, `plain.toolbar`)
and override the default when their `templates.py` registers via
`@register_global`.

Today only `toolbar` is genuinely optional (admin works with or without
`plain.toolbar`). The others are package-specific and don't need a
default — if a template uses `tailwind_css()` it should require
`plain.tailwind`.
"""

from __future__ import annotations

from typing import Any

from plain.utils.safestring import SafeString, mark_safe


def toolbar(request: Any) -> SafeString:
    """No-op default. plain.toolbar's templates.py overrides this when installed."""
    return mark_safe("")
