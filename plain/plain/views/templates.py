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
        '<input type="hidden" name="csrfmiddlewaretoken" value="{}">',
        get_token(request),
    )


csrf_input_lazy = lazy(csrf_input, SafeString, str)
csrf_token_lazy = lazy(get_token, str)


class TemplateView(View):
    """
    Render a template. Pass keyword arguments from the URLconf to the context.
    """

    template_name: str | None = None

    def get_template_context(self) -> dict:
        return {
            "request": self.request,
            "csrf_input": csrf_input_lazy(self.request),
            "csrf_token": csrf_token_lazy(self.request),
            "DEBUG": settings.DEBUG,
        }

    def get_template_names(self) -> list[str]:
        """
        Return a list of template names to be used for the request. Must return
        a list. May not be called if render_to_response() is overridden.
        """
        if self.template_name is None:
            raise ImproperlyConfigured(
                "TemplateView requires either a definition of "
                "'template_name' or an implementation of 'get_template_names()'"
            )
        else:
            return [self.template_name]

    def get_template(self) -> Template:
        template_names = self.get_template_names()

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
