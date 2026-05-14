"""plain.html — HTML-aware template engine with contextual autoescape."""

from __future__ import annotations

from plain.utils.safestring import SafeString as Markup

# `mark_safe` is the canonical name in user-facing Python code. `Markup` is
# the same callable, kept for spec-consistency: templates can write either,
# since the compiled module exposes both names in render scope.
from plain.utils.safestring import mark_safe

from .compiler import CompileError
from .engine import render, render_source
from .loader import TemplateFileMissing
from .parser import ParseError
from .template import Template
from .tokenizer import TokenizeError
from .views import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    NotFoundView,
    TemplateView,
    UpdateView,
)

__all__ = [
    "CompileError",
    "CreateView",
    "DeleteView",
    "DetailView",
    "FormView",
    "ListView",
    "Markup",
    "NotFoundView",
    "ParseError",
    "Template",
    "TemplateFileMissing",
    "TemplateView",
    "TokenizeError",
    "UpdateView",
    "mark_safe",
    "render",
    "render_source",
]
