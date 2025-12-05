from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.http import Response
from plain.runtime import settings
from plain.templates import Template, TemplateFileMissing

from .base import View


class TemplateView(View):
    """
    Render a template.
    """

    template_name: str | None = None

    def __init__(self, template_name: str | None = None) -> None:
        # Allow template_name to be passed in as_view()
        self.template_name = template_name or self.template_name

    def get_template_context(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "template_names": self.get_template_names(),
            "DEBUG": settings.DEBUG,
        }

    def get_template_names(self) -> list[str]:
        """
        Return a list of template names to be used for the request.
        """
        if self.template_name:
            return [self.template_name]

        return []

    def get_template(self) -> Template:
        template_names = self.get_template_names()

        if isinstance(template_names, str):
            raise ImproperlyConfigured(
                f"{self.__class__.__name__}.get_template_names() must return a list of strings, "
                f"not a string. Did you mean to return ['{template_names}']?"
            )

        if not template_names:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} requires a template_name or get_template_names()."
            )

        for template_name in template_names:
            try:
                return Template(template_name)
            except TemplateFileMissing:
                pass

        raise TemplateFileMissing(template_names)

    def render_template(self) -> str:
        return self.get_template().render(self.get_template_context())

    def get(self) -> Response | Any:
        return Response(self.render_template())
