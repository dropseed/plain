"""Engine-wide globals injected into every render scope.

Packages add their helpers by mutating this dict (similar to Jinja's
`environment.globals`). The plain.templates integration registers Plain's
default globals — URL helpers, asset URLs, paginator, time helpers — so
templates can call `{url("home")}`, `{asset("css/app.css")}`, etc.
without per-template imports.
"""

from __future__ import annotations

from typing import Any

_GLOBALS: dict[str, Any] = {}
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
    """Pull Plain's default Jinja globals into the plain.html scope so the same
    helpers (`url`, `asset`, `reverse`, etc.) are available in both engines.
    Also picks up anything registered via `register_template_global` (e.g.
    `is_package_installed`, `get_current_session`) and exposes the
    package-helper shims (`tailwind_css`, `pageviews_js`, `toolbar`) that
    bridge to Jinja-rendered package templates until those are ported.
    """
    try:
        from plain.templates.jinja import environment
        from plain.templates.jinja.globals import default_globals
    except ImportError:
        return
    for name, value in default_globals.items():
        _GLOBALS.setdefault(name, value)
    # Trigger Jinja env setup and pull anything `register_template_global`
    # added on top of the defaults.
    try:
        for name, value in environment.globals.items():  # type: ignore[attr-defined]
            _GLOBALS.setdefault(name, value)
    except Exception:
        pass

    from plain.utils.safestring import SafeString, mark_safe

    _GLOBALS.setdefault("mark_safe", mark_safe)
    _GLOBALS.setdefault("Markup", SafeString)

    from . import _shims

    _GLOBALS.setdefault("tailwind_css", _shims.tailwind_css)
    _GLOBALS.setdefault("pageviews_js", _shims.pageviews_js)
    _GLOBALS.setdefault("htmx_js", _shims.htmx_js)
    _GLOBALS.setdefault("toolbar", _shims.toolbar)
