import jinja2

from .jinja import environment


class TemplateFileMissing(Exception):
    pass


class Template:
    def __init__(self, filename: str) -> None:
        self.filename = filename

        try:
            self._jinja_template = environment.get_template(filename)
        except jinja2.TemplateNotFound:
            raise TemplateFileMissing(f"Template file {filename} not found")

    def render(self, context: dict) -> str:
        return self._jinja_template.render(context)
