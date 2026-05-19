"""plain.html — HTML-aware template engine with contextual autoescape."""

from __future__ import annotations

from plain.utils.safestring import SafeString as Markup
from plain.utils.safestring import mark_safe

from .compiler import CompileError
from .engine import render, render_source, render_text_source
from .loader import TemplateFileMissing
from .parser import ParseError
from .template import Template
from .tokenizer import TokenizeError
from .views import (
    DetailView,
    ListView,
    NotFoundView,
    TemplateView,
)

__all__ = [
    "CompileError",
    "DetailView",
    "ListView",
    "Markup",
    "NotFoundView",
    "ParseError",
    "Template",
    "TemplateFileMissing",
    "TemplateView",
    "TokenizeError",
    "mark_safe",
    "render",
    "render_source",
    "render_text_source",
]
