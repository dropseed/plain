from django.core.exceptions import ImproperlyConfigured
from bolt.http import HttpResponse

from .base import View
from bolt import jinja
from bolt.jinja.context import csrf_input_lazy, csrf_token_lazy
import jinja2


class TemplateDoesNotExist(Exception):
    pass


class TemplateView(View):
    """
    Render a template. Pass keyword arguments from the URLconf to the context.
    """

    template_name: str | None = None
    content_type: str | None = None

    def get_template_response(self, context=None, **response_kwargs) -> "TemplateResponse":
        if context is None:
            context = self.get_context()

        response_kwargs.setdefault("content_type", self.content_type)

        return TemplateResponse(
            template=self.get_template(),
            context=context,
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

    def get_template(self) -> jinja2.Template:
        template_names = self.get_template_names()
        return jinja.environment.get_or_select_template(template_names)

    def get_context(self) -> dict:
        return {
            "request": self.request,
            "csrf_input": csrf_input_lazy(self.request),
            "csrf_token": csrf_token_lazy(self.request),
        }

    def get(self):
        return self.get_template_response()


class ContentNotRenderedError(Exception):
    pass


class TemplateResponse(HttpResponse):
    non_picklable_attrs = HttpResponse.non_picklable_attrs | frozenset(
        ["template_name", "context_data", "_post_render_callbacks", "_request"]
    )

    def __init__(
        self,
        template,
        context=None,
        content_type=None,
        status=None,
        charset=None,
        headers=None,
    ):
        self.jinja_template = template

        # It would seem obvious to call these next two members 'template' and
        # 'context', but those names are reserved as part of the test Client
        # API. To avoid the name collision, we use different names.
        self.context_data = context

        self._post_render_callbacks = []

        # content argument doesn't make sense here because it will be replaced
        # with rendered template so we always pass empty string in order to
        # prevent errors and provide shorter signature.
        super().__init__("", content_type, status, charset=charset, headers=headers)

        # _is_rendered tracks whether the template and context has been baked
        # into a final response.
        # Super __init__ doesn't know any better than to set self.content to
        # the empty string we just gave it, which wrongly sets _is_rendered
        # True, so we initialize it to False after the call to super __init__.
        self._is_rendered = False

    def __getstate__(self):
        """
        Raise an exception if trying to pickle an unrendered response. Pickle
        only rendered data, not the data used to construct the response.
        """
        if not self._is_rendered:
            raise ContentNotRenderedError(
                "The response content must be rendered before it can be pickled."
            )
        return super().__getstate__()

    @property
    def rendered_content(self):
        """Return the freshly rendered content for the template and context
        described by the TemplateResponse.

        This *does not* set the final content of the response. To set the
        response content, you must either call render(), or set the
        content explicitly using the value of this property.
        """
        return self.jinja_template.render(self.context_data)

    def add_post_render_callback(self, callback):
        """Add a new post-rendering callback.

        If the response has already been rendered,
        invoke the callback immediately.
        """
        if self._is_rendered:
            callback(self)
        else:
            self._post_render_callbacks.append(callback)

    def render(self):
        """Render (thereby finalizing) the content of the response.

        If the content has already been rendered, this is a no-op.

        Return the baked response instance.
        """
        retval = self
        if not self._is_rendered:
            self.content = self.rendered_content
            for post_callback in self._post_render_callbacks:
                newretval = post_callback(retval)
                if newretval is not None:
                    retval = newretval
        return retval

    @property
    def is_rendered(self):
        return self._is_rendered

    def __iter__(self):
        if not self._is_rendered:
            raise ContentNotRenderedError(
                "The response content must be rendered before it can be iterated over."
            )
        return super().__iter__()

    @property
    def content(self):
        if not self._is_rendered:
            raise ContentNotRenderedError(
                "The response content must be rendered before it can be accessed."
            )
        return super().content

    @content.setter
    def content(self, value):
        """Set the content for the response."""
        HttpResponse.content.fset(self, value)
        self._is_rendered = True
