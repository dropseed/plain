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
    """Render either a Jinja `.html` template or a `plain.html` `.plain` template.

    The decision is filename-driven: anything ending in `.plain` goes through
    `plain.html`; everything else routes to the existing Jinja environment.
    During migration both engines coexist; a view can render `.html` or
    `.plain` and views above don't care which.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self._plain_path: Path | None = None
        self._jinja_template = None

        if filename.endswith(".plain"):
            self._plain_path = self._find_plain(filename)
            if self._plain_path is None:
                raise TemplateFileMissing(filename)
            return

        try:
            self._jinja_template = environment.get_template(filename)
        except jinja2.TemplateNotFound:
            raise TemplateFileMissing(filename)

    @staticmethod
    def _find_plain(filename: str) -> Path | None:
        from plain.html.loader import TemplateNotFound, find_template

        name = filename.removesuffix(".plain")
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
