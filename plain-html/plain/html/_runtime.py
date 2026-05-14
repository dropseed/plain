"""Runtime helpers called by compiled template modules.

Each compiled template imports from this module. The helpers handle the
work the codegen doesn't inline: contextual escaping, boolean / list
attribute rendering, dynamic `:include` resolution, and Python-keyword
aliasing of attr names.
"""

from __future__ import annotations

import html as _html
import keyword
from collections.abc import Callable, Iterable
from typing import cast

from plain.utils.html import conditional_escape
from plain.utils.safestring import SafeString

# Module-local alias kept hot in the closure — `html.escape` is by far the
# common case and we want to skip the LOAD_GLOBAL chain `_html.escape`.
_html_escape = _html.escape


# Built-in numeric/bool types whose `str(...)` form is guaranteed to contain
# no HTML-special characters — skipping `html.escape` on them is correct and
# saves a real chunk of time in expression-heavy templates.
_NUMERIC_TYPES = (int, float, bool)


def escape_html(value: object) -> str:
    """Render a value for HTML text content.

    Hot paths:
      - `str` → `html.escape(value)` directly
      - `SafeString` → returned as-is (already escaped)
      - `None` → `""`
      - `int` / `float` / `bool` → `str(value)` (no HTML specials possible)

    Anything else falls back to the general `conditional_escape` path
    (lazy promises, objects with `__html__`, custom types). The fast
    paths cover the 95% case and skip the per-call overhead
    `conditional_escape` adds.
    """
    if value is None:
        return ""
    # `type is X` checks (not `isinstance`) — SafeString subclasses str
    # but we want it on a separate branch so raw str hits `html.escape`
    # without an extra dispatch.
    t = type(value)
    if t is str:
        return _html_escape(cast(str, value))
    if t is SafeString:
        return cast(str, value)
    if t in _NUMERIC_TYPES:
        return str(value)
    return str(conditional_escape(value))


def escape_attr(value: object) -> str:
    """Render a value for an HTML attribute value (between quotes)."""
    if value is None:
        return ""
    t = type(value)
    if t is str:
        return _html_escape(cast(str, value))
    if t is SafeString:
        return cast(str, value)
    if t in _NUMERIC_TYPES:
        return str(value)
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
    if type(value) is str:
        text = value
    else:
        text = str(value)
    # Strip leading whitespace only if there's any — common-case relative
    # URLs (`/foo`, `bar`) don't have any and the check is faster than
    # always calling `.lstrip()`.
    if text and text[0] in " \t\n\r\f\v":
        text = text.lstrip()
    # Hot path: relative URL — first non-special char is `/`, `?`, `#`, or
    # the string starts with `\`. Skip the scheme loop entirely. This is
    # by far the most common shape for `href=` / `src=` in app templates.
    if text and text[0] in "/?#\\":
        return _html_escape(text)
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
    return _html_escape(text)


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
