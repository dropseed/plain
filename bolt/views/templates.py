from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.template.response import TemplateResponse

from .base import View


class TemplateView(View):
    """
    Render a template. Pass keyword arguments from the URLconf to the context.
    """

    template_name: str | None = None
    template_engine = None
    response_class = TemplateResponse
    content_type: str | None = None

    def render_to_response(self, context, **response_kwargs) -> HttpResponse:
        """
        Return a response, using the `response_class` for this view, with a
        template rendered with the given context.

        Pass response_kwargs to the constructor of the response class.
        """
        response_kwargs.setdefault("content_type", self.content_type)
        return self.response_class(
            request=self.request,
            template=self.get_template_names(),
            context=context,
            using=self.template_engine,
            **response_kwargs,
        )

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

    def get_context_data(self) -> dict:
        return {}

    def get(self):
        context = self.get_context_data()
        return self.render_to_response(context)
