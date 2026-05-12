"""plain.html — HTML-aware template engine.

Phase 0 tracer bullet: minimal end-to-end render path for a single template
with `{expr}` interpolation, `:if`/`:for` directives, attribute interpolation,
and HTML-escape. Used to validate the spec against real templates and produce
a parity diff against Jinja output.

Eventually replaced by the full pipeline described in the implementation plan:
frontmatter parser → tokenizer → tag tree builder → compile-to-Python →
contextual autoescape → loader → static checker.
"""

from __future__ import annotations

from plain.utils.safestring import SafeString as Markup
from plain.utils.safestring import mark_safe

from .engine import render, render_source

__all__ = ["render", "render_source", "Markup", "mark_safe"]
