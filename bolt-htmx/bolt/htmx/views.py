import re

from django.http import HttpResponse


class HTMXViewMixin:
    htmx_template_name = ""

    def get_template_response(self, context=None) -> HttpResponse:
        if self.is_htmx_request and self.htmx_fragment_name:
            from .jinja import HTMXFragmentExtension
            template = self.get_template()
            if context is None:
                context = self.get_context()
            rendered = HTMXFragmentExtension.render_template_fragment(
                template=template,
                fragment_name=self.htmx_fragment_name,
                context=context,
            )
            return HttpResponse(rendered, content_type=self.content_type)

        return super().get_template_response(context=context)

    def dispatch(self):
        if self.is_htmx_request:
            # You can use an htmx_{method} method on views
            # (or htmx_{method}_{action} for specific actions)
            method = f"htmx_{self.request.method.lower()}"
            if self.htmx_action_name:
                method += f"_{self.htmx_action_name}"

            handler = getattr(self, method, None)
            if handler:
                return handler()

        return super().dispatch()

    def get_template_names(self):
        # TODO is this part necessary anymore?? can I replace those with fragments now?
        if self.is_htmx_request:
            if self.htmx_template_name:
                return [self.htmx_template_name]

            default_template_names = super().get_template_names()
            return [
                re.sub(r"\.html$", "_htmx.html", template_name)
                for template_name in default_template_names
            ] + default_template_names  # Fallback to the defaults so you don't need _htmx.html

        return super().get_template_names()

    @property
    def is_htmx_request(self):
        return self.request.headers.get("HX-Request") == "true"

    @property
    def htmx_fragment_name(self):
        # A custom header that we pass with the {% htmxfragment %} tag
        return self.request.headers.get("BHX-Fragment", "")

    @property
    def htmx_action_name(self):
        return self.request.headers.get("BHX-Action", "")
