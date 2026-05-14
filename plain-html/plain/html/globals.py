"""Engine-wide globals injected into every render scope.

Templates have URL helpers, time helpers, `mark_safe`/`Markup`, and the
package-shim helpers (`tailwind_css`, `htmx_js`, etc.) available without
declaring them in their `imports:` block. Packages add their own globals
via `register()` / `@register_global`.
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


def register_global[T](func: T, *, name: str | None = None) -> T:
    """Decorator form: register a callable as a template global.

    The name defaults to the callable's `__name__`.
    """
    _GLOBALS[name or func.__name__] = func  # ty: ignore[unresolved-attribute]
    return func


def all_globals() -> dict[str, Any]:
    """Return a copy of the global registry, loading Plain defaults on first call."""
    global _DEFAULTS_LOADED
    if not _DEFAULTS_LOADED:
        _DEFAULTS_LOADED = True
        _load_defaults()
    return dict(_GLOBALS)


def _load_defaults() -> None:
    """Register the no-op fallback for the optional `toolbar()` global and
    autodiscover each installed package's `templates.py` so its
    `@register_global` calls fire.

    The package-helper globals (`tailwind_css`, `htmx_js`, `pageviews_js`,
    `toolbar`) live in their home packages now — `plain.tailwind`,
    `plain.htmx`, etc. Autodiscovery imports the module, the decorator
    runs, the global is registered.
    """
    from plain.packages import packages_registry

    from . import _shims

    # `toolbar()` is genuinely optional — admin works with or without
    # `plain.toolbar`. Set a no-op default before autodiscovery so that
    # `{toolbar(request)}` in a template doesn't NameError when
    # plain.toolbar isn't installed. plain.toolbar's `templates.py`
    # overrides this with the real implementation when present.
    _GLOBALS.setdefault("toolbar", _shims.toolbar)

    # Import each installed package's `templates` submodule so any
    # `@register_global` / `register()` calls run. Side-effect imports,
    # but matches the pattern Jinja used and keeps package authors from
    # having to manage import order by hand.
    packages_registry.autodiscover_modules("templates", include_app=True)
