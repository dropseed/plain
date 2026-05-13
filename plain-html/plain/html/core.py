"""Template-by-name convenience wrapper.

`render()` takes a file path; `Template(name)` lets callers (`TemplateView`,
the admin's per-field value rendering, toolbar items) work with template
names and look up the path lazily.
"""

from __future__ import annotations

from pathlib import Path

from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import CODE_FUNCTION_NAME

from .engine import render
from .loader import TemplateNotFound

tracer = trace.get_tracer("plain.html")


class TemplateFileMissing(Exception):
    def __str__(self) -> str:
        if self.args:
            return f"Template file {self.args[0]} not found"
        else:
            return "Template file not found"


class Template:
    """A named template ready to render.

    Resolves `name` to a `.html` file under an `html/` directory at
    construction time so callers can detect missing templates eagerly
    via `TemplateFileMissing`. Rendering goes through `plain.html.render`.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        try:
            from .loader import find_template

            self.path: Path = find_template(name)
        except TemplateNotFound:
            raise TemplateFileMissing(name)

    def render(self, context: dict) -> str:
        with tracer.start_as_current_span(
            f"render {self.name}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                CODE_FUNCTION_NAME: f"{self.__class__.__module__}.{self.__class__.__qualname__}.render",
                "template.filename": self.name,
                "template.engine": "plain.html",
            },
        ):
            return render(self.path, context)
