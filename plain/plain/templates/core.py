import jinja2
from opentelemetry import trace

from .jinja import environment

tracer = trace.get_tracer(__name__)


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
                "code.function.name": "render",
                "code.namespace": f"{self.__class__.__module__}.{self.__class__.__qualname__}",
                "template.filename": self.filename,
                "template.engine": "jinja2",
            },
        ) as span:
            try:
                result = self._jinja_template.render(context)
                span.set_status(trace.StatusCode.OK)
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))
                raise
