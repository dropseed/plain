from plain.csrf.middleware import get_token
from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings
from plain.templates import Template, TemplateFileMissing
from plain.utils.functional import lazy
from plain.utils.html import format_html
from plain.utils.safestring import SafeString

from .base import View


def csrf_input(request):
    return format_html(
        '<input type="hidden" name="{}" value="{}">',
        settings.CSRF_FIELD_NAME,
        get_token(request),
    )


csrf_input_lazy = lazy(csrf_input, SafeString, str)
csrf_token_lazy = lazy(get_token, str)


class TemplateView(View):
    """
    Render a template.
    """

    template_name: str | None = None

    def __init__(self, template_name=None):
        # Allow template_name to be passed in as_view()
        self.template_name = template_name or self.template_name

    def get_template_context(self) -> dict:
        return {
            "request": self.request,
            "template_names": self.get_template_names(),
            "csrf_input": csrf_input_lazy(self.request),
            "csrf_token": csrf_token_lazy(self.request),
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

    def get(self):
        return self.render_template()
