import jinja2

from .jinja import environment


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
        return self._jinja_template.render(context)
