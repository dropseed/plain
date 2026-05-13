from pathlib import Path

import jinja2
from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
)

from .jinja import environment

tracer = trace.get_tracer("plain.templates")


class TemplateFileMissing(Exception):
    def __str__(self) -> str:
        if self.args:
            return f"Template file {self.args[0]} not found"
        else:
            return "Template file not found"


class Template:
    """Render either a plain.html template or a Jinja template, picking based
    on disk presence.

    Resolution order: for any `.html` name, check whether plain.html can
    resolve it (via its `html/` discovery, with a transitional fallback to
    `.plain.html` under `templates/`). If yes, render through plain.html.
    Otherwise fall back to the Jinja environment.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self._plain_path: Path | None = None
        self._jinja_template = None

        if filename.endswith(".html"):
            plain_path = self._find_plain(filename.removesuffix(".html"))
            if plain_path is not None:
                self._plain_path = plain_path
                return

        try:
            self._jinja_template = environment.get_template(filename)
        except jinja2.TemplateNotFound:
            raise TemplateFileMissing(filename)

    @staticmethod
    def _find_plain(name: str) -> Path | None:
        try:
            from plain.html.loader import TemplateNotFound, find_template
        except ImportError:
            # plain.html is an optional companion during migration —
            # without it, fall through to Jinja resolution.
            return None
        try:
            return find_template(name)
        except TemplateNotFound:
            return None

    def render(self, context: dict) -> str:
        engine = "plain.html" if self._plain_path is not None else "jinja2"
        with tracer.start_as_current_span(
            f"render {self.filename}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                CODE_FUNCTION_NAME: f"{self.__class__.__module__}.{self.__class__.__qualname__}.render",
                "template.filename": self.filename,
                "template.engine": engine,
            },
        ):
            if self._plain_path is not None:
                from plain.html import render as plain_render

                return plain_render(self._plain_path, context)
            assert self._jinja_template is not None
            return self._jinja_template.render(context)
