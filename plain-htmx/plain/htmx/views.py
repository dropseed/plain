import re

from plain.utils.cache import patch_vary_headers

from .templates import render_template_fragment


class HTMXViewMixin:
    htmx_template_name = ""

    def render_template(self):
        template = self.get_template()
        context = self.get_template_context()

        if self.is_htmx_request and self.htmx_fragment_name:
            return render_template_fragment(
                template=template._jinja_template,
                fragment_name=self.htmx_fragment_name,
                context=context,
            )

        return template.render(context)

    def get_response(self):
        response = super().get_response()
        # Tell browser caching to also consider the fragment header,
        # not just the url/cookie.
        patch_vary_headers(
            response, ["HX-Request", "Plain-HX-Fragment", "Plain-HX-Action"]
        )
        return response

    def get_request_handler(self):
        if self.is_htmx_request:
            # You can use an htmx_{method} method on views
            # (or htmx_{method}_{action} for specific actions)
            method = f"htmx_{self.request.method.lower()}"
            if self.htmx_action_name:
                method += f"_{self.htmx_action_name}"

            if handler := getattr(self, method, None):
                return handler

        return super().get_request_handler()

    def get_template_names(self):
        # TODO is this part necessary anymore?? can I replace those with fragments now?
        if self.is_htmx_request:
            if self.htmx_template_name:
                return [self.htmx_template_name]

            default_template_names = super().get_template_names()
            return (
                [
                    re.sub(r"\.html$", "_htmx.html", template_name)
                    for template_name in default_template_names
                ]
                + default_template_names
            )  # Fallback to the defaults so you don't need _htmx.html

        return super().get_template_names()

    @property
    def is_htmx_request(self):
        return self.request.headers.get("HX-Request") == "true"

    @property
    def htmx_fragment_name(self):
        # A custom header that we pass with the {% htmxfragment %} tag
        return self.request.headers.get("Plain-HX-Fragment", "")

    @property
    def htmx_action_name(self):
        return self.request.headers.get("Plain-HX-Action", "")
