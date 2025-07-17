import jinja2
from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
    CODE_NAMESPACE,
)

from .jinja import environment

tracer = trace.get_tracer("plain")


class TemplateFileMissing(Exception):
    def __str__(self) -> str:
        if self.args:
            return f"Template file {self.args[0]} not found"
        else:
            return "Template file not found"


class Template:
    def __init__(self, filename: str) -> None:
        self.filename = filename

        try:
            self._jinja_template = environment.get_template(filename)
        except jinja2.TemplateNotFound:
            raise TemplateFileMissing(filename)

    def render(self, context: dict) -> str:
        with tracer.start_as_current_span(
            f"render {self.filename}",
            kind=trace.SpanKind.INTERNAL,
            attributes={
                CODE_FUNCTION_NAME: "render",
                CODE_NAMESPACE: f"{self.__class__.__module__}.{self.__class__.__qualname__}",
                "template.filename": self.filename,
                "template.engine": "jinja2",
            },
        ):
            result = self._jinja_template.render(context)
            return result
