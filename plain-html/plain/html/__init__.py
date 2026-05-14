"""plain.html — HTML-aware template engine with contextual autoescape."""

from __future__ import annotations

from plain.utils.safestring import SafeString as Markup

# `mark_safe` is the canonical name in user-facing Python code. `Markup` is
# the same callable, kept for spec-consistency: templates can write either,
# since the compiled module exposes both names in render scope.
from plain.utils.safestring import mark_safe

from .engine import render, render_source
from .loader import TemplateFileMissing
from .template import Template

__all__ = [
    "mark_safe",
    "Markup",
    "Template",
    "TemplateFileMissing",
    "render",
    "render_source",
]
