"""Runtime helpers called by compiled template modules.

Each compiled template imports from this module. The helpers handle the
work the codegen doesn't inline: contextual escaping, boolean / list
attribute rendering, dynamic `:include` resolution, and Python-keyword
aliasing of attr names.
"""

from __future__ import annotations

import keyword
from collections.abc import Callable, Iterable

from plain.utils.html import conditional_escape


def escape_html(value: object) -> str:
    """Render a value for HTML text content.

    Mirrors `engine._escape_to_str`: `None` → `""`, everything else runs
    through `conditional_escape` (which respects `SafeString`).
    """
    if value is None:
        return ""
    return str(conditional_escape(value))


def escape_attr(value: object) -> str:
    """Render a value for an HTML attribute value (between quotes)."""
    if value is None:
        return ""
    return str(conditional_escape(value))


# URL schemes considered safe for href/src/action/etc. Anything else (notably
# `javascript:` and `data:`) becomes an empty string so the resulting markup
# can't navigate to or execute attacker-controlled code.
SAFE_URL_SCHEMES: frozenset[str] = frozenset(
    {"http", "https", "mailto", "tel", "ftp", "ftps"}
)


def escape_url(value: object) -> str:
    """Render a value for a URL-bearing attribute (`href`, `src`, …).

    Validates the scheme against `SAFE_URL_SCHEMES`. A value whose
    scheme is not on the allow-list is replaced with the empty string —
    better an empty link than an XSS sink. Relative URLs (no scheme)
    pass through; the value is finally HTML-escaped for attribute
    context.
    """
    if value is None:
        return ""
    text = str(value).lstrip()
    # Locate the scheme separator without picking up colons that belong to
    # a path/query/fragment: stop at the first `/`, `?`, `#`, or `\`.
    colon = -1
    for idx, ch in enumerate(text):
        if ch == ":":
            colon = idx
            break
        if ch in "/?#\\":
            break
    if colon > 0 and text[:colon].lower() not in SAFE_URL_SCHEMES:
        return ""
    return escape_attr(text)


def render_dyn_attr(name: str, value: object) -> str:
    """Render a `name={expr}` attribute with boolean/list/None semantics.

    Returns the full ` name="value"` chunk, ` name` for `True`, or the
    empty string to omit the attribute. Matches `engine._render_attribute`
    for the single-expression case.
    """
    if value is False or value is None:
        return ""
    if value is True:
        return f" {name}"
    if isinstance(value, list):
        parts = [str(v) for v in _flatten(value) if v]
        if not parts:
            return ""
        return f' {name}="{escape_attr(" ".join(parts))}"'
    return f' {name}="{escape_attr(value)}"'


def render_dyn_url_attr(name: str, value: object) -> str:
    """Same shape as `render_dyn_attr` but routes through `escape_url`.

    Used for URL-bearing attributes (`href`, `src`, …). Boolean / `None`
    values still omit the attribute. List values are rejected (URL attrs
    don't have the multi-class join shape that HTML class lists do) —
    they collapse to the joined string and run through `escape_url`,
    which will probably refuse the result.
    """
    if value is False or value is None:
        return ""
    if value is True:
        return f" {name}"
    if isinstance(value, list):
        parts = [str(v) for v in _flatten(value) if v]
        if not parts:
            return ""
        joined = " ".join(parts)
        safe = escape_url(joined)
        if not safe:
            return ""
        return f' {name}="{safe}"'
    safe = escape_url(value)
    if not safe:
        return ""
    return f' {name}="{safe}"'


def resolve_dynamic_include(name: str, *, current_template: str) -> Callable[..., str]:
    """Resolve a `<template :include={expr}>` site at render time.

    Looks the name up via `loader.find_template` (relative to the
    calling template, matching the static-include resolver), then asks
    the compiler for a cached compiled `render` function. Imports are
    deferred to avoid an import cycle — this module is the one every
    compiled template imports from.
    """
    from pathlib import Path

    from .compiler import get_or_compile
    from .loader import find_template

    target = find_template(name, current_template=Path(current_template))
    return get_or_compile(target)


def normalize_keywords(scope: dict) -> None:
    """Alias Python-keyword-named entries under a trailing-underscore name.

    Matches `engine._build_scope`: a template attr passed as `class="x"`
    becomes accessible as `class_` in `{...}` expressions, since `class`
    is unreferenceable in Python.
    """
    for name in list(scope.keys()):
        if keyword.iskeyword(name):
            scope.setdefault(f"{name}_", scope[name])


def _flatten(value: object) -> Iterable[object]:
    if isinstance(value, list | tuple):
        for item in value:
            yield from _flatten(item)
    else:
        yield value
