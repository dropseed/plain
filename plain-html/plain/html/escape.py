"""Contextual autoescape primitives.

Phase 0 scope: HTML body escape and attribute-value escape. URL validation,
script/style refusal, and class-list/splat flattening get layered in later.
"""

from __future__ import annotations

from plain.utils.safestring import SafeString


def escape_html(value: object) -> str:
    """Escape a value for emission into an HTML text body.

    ``SafeString`` values are passed through unchanged. ``None`` becomes the
    empty string. Everything else is stringified and HTML-escaped, including
    quotes (so the same escape is safe for attribute values).
    """
    if value is None:
        return ""
    if isinstance(value, SafeString):
        return str(value)
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&#34;")
        .replace("'", "&#39;")
    )


def escape_attr(value: object) -> str:
    """Escape a value for emission as an attribute value (inside double quotes)."""
    return escape_html(value)
