"""plain.html — HTML-aware template engine with contextual autoescape."""

from __future__ import annotations

from plain.utils.safestring import SafeString as Markup
from plain.utils.safestring import mark_safe

from .core import Template, TemplateFileMissing
from .engine import render, render_source

__all__ = [
    "Markup",
    "Template",
    "TemplateFileMissing",
    "mark_safe",
    "render",
    "render_source",
]
