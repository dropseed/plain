from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

from .base import View
from django.bolt import jinja
from django.bolt.jinja.context import csrf_input_lazy, csrf_token_lazy
import jinja2


class TemplateDoesNotExist(Exception):
    pass


class TemplateView(View):
    """
    Render a template. Pass keyword arguments from the URLconf to the context.
    """

    template_name: str | None = None
    content_type: str | None = None

    def render_template_response(self, extra_context={}) -> HttpResponse:
        template = self.get_template()
        context = self.get_context_data()
        context.update(extra_context)
        return HttpResponse(template.render(context), content_type=self.content_type)

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

    def get_template(self) -> jinja2.Template:
        template_names = self.get_template_names()

        for template_name in template_names:
            try:
                return jinja.env.get_template(template_name)
            except jinja2.TemplateNotFound:
                pass

        raise TemplateDoesNotExist(f"Template {template_names} does not exist.")

    def get_context_data(self) -> dict:
        return {
            "request": self.request,
            "csrf_input": csrf_input_lazy(self.request),
            "csrf_token": csrf_token_lazy(self.request),
        }

    def get(self):
        return self.render_template_response()
