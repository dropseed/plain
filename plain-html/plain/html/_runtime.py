"""Runtime helpers called by compiled template modules.

Phase 5 codegen emits calls into this module. The functions here match
the interpreter's behavior byte-for-byte so the compiler's output stays
equivalent to `engine.render_source(...)` across the entire corpus.

Phase 6 will introduce position-aware escape variants. The names
(`escape_html`, `escape_attr`) stay stable so that's a function-body
swap, not a codegen change.
"""

from __future__ import annotations

import keyword
from collections.abc import Iterable

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
