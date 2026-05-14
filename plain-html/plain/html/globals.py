"""Engine-wide globals injected into every render scope.

Templates have URL helpers, time helpers, `mark_safe`/`Markup`, and the
package-shim helpers (`tailwind_css`, `htmx_js`, etc.) available without
declaring them in their `imports:` block. Packages can add their own
globals via `register()`; transitionally we also pull in anything
plain.templates.jinja registered via `@register_template_global` so
existing callers keep working.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from plain.paginator import Paginator
from plain.urls import absolute_url, reverse, reverse_absolute
from plain.utils import timezone
from plain.utils.safestring import SafeString, mark_safe

_GLOBALS: dict[str, Any] = {
    # URL helpers
    "url": reverse,
    "reverse": reverse,
    "reverse_absolute": reverse_absolute,
    "absolute_url": absolute_url,
    # Pagination
    "Paginator": Paginator,
    # Time helpers
    "now": timezone.now,
    "timedelta": timedelta,
    "localtime": timezone.localtime,
    # Markup / safety
    "mark_safe": mark_safe,
    "Markup": SafeString,
}
_DEFAULTS_LOADED = False


def register(name: str, value: Any) -> None:
    """Register a value or callable as a template global."""
    _GLOBALS[name] = value


def register_many(values: dict[str, Any]) -> None:
    _GLOBALS.update(values)


def all_globals() -> dict[str, Any]:
    """Return a copy of the global registry, loading Plain defaults on first call."""
    global _DEFAULTS_LOADED
    if not _DEFAULTS_LOADED:
        _DEFAULTS_LOADED = True
        _load_defaults()
    return dict(_GLOBALS)


def _load_defaults() -> None:
    """Pick up Jinja-side `@register_template_global` entries and bind the
    package-helper shims (`tailwind_css`, `htmx_js`, `pageviews_js`,
    `toolbar`) onto the plain.html scope. Both halves are transitional —
    the Jinja scan goes away once every package switches to plain.html
    registration; the shims move into their home packages once templates
    learn to `imports:` them.
    """
    try:
        from plain.templates.jinja import environment
    except ImportError:
        pass
    else:
        try:
            for name, value in environment.globals.items():  # type: ignore[attr-defined]
                _GLOBALS.setdefault(name, value)
        except Exception:
            pass

    from . import _shims

    _GLOBALS.setdefault("tailwind_css", _shims.tailwind_css)
    _GLOBALS.setdefault("pageviews_js", _shims.pageviews_js)
    _GLOBALS.setdefault("htmx_js", _shims.htmx_js)
    _GLOBALS.setdefault("toolbar", _shims.toolbar)
