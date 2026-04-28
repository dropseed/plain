from __future__ import annotations

from collections.abc import Callable
from http import HTTPMethod
from typing import Any

from plain.http import Response
from plain.utils.cache import patch_vary_headers
from plain.views import TemplateView

from .templates import render_template_fragment

__all__ = ["HTMXView"]


class HTMXView(TemplateView):
    """View with HTMX-specific functionality.

    Action handlers (`htmx_post_<action>` etc.) may return `None` to mean
    "re-render the current template (or active fragment)". Return an
    explicit `Response` only when the action diverges from a re-render —
    e.g. a redirect, a 204, or a custom payload.
    """

    def render_template(self) -> str:
        template = self.get_template()
        context = self.get_template_context()

        if self.is_htmx_request() and self.get_htmx_fragment_name():
            return render_template_fragment(
                template=template._jinja_template,
                fragment_name=self.get_htmx_fragment_name(),
                context=context,
            )

        return template.render(context)

    def convert_result_to_response(self, result: Response | None) -> Response:
        if result is None:
            return Response(self.render_template())
        if isinstance(result, Response):
            return result
        raise TypeError(
            f"{type(self).__name__} action handlers must return a Response or None "
            f"(got {type(result).__name__}). "
            "Return None to re-render the current template/fragment, or a Response "
            "to diverge (redirect, 204, custom payload)."
        )

    def after_response(self, response: Response) -> Response:
        response = super().after_response(response)
        # Tell browser caching to also consider the fragment header,
        # not just the url/cookie.
        patch_vary_headers(
            response, ["HX-Request", "Plain-HX-Fragment", "Plain-HX-Action"]
        )
        return response

    def get_request_handler(self) -> Callable[[], Any] | None:
        if (
            self.is_htmx_request()
            and self.request.method
            and self.request.method in HTTPMethod.__members__
        ):
            # You can use an htmx_{method} method on views
            # (or htmx_{method}_{action} for specific actions)
            method = f"htmx_{self.request.method.lower()}"

            if action := self.get_htmx_action_name():
                # Action must be a plain identifier to be a valid attribute name
                if not action.isidentifier():
                    return None
                return getattr(self, f"{method}_{action}", None)

            if handler := getattr(self, method, None):
                # If it's just an htmx post, for example,
                # we can use a custom method or we can let it fall back
                # to a regular post method if it's not found
                return handler

        return super().get_request_handler()

    def is_htmx_request(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    def get_htmx_fragment_name(self) -> str:
        # A custom header that we pass with the {% htmxfragment %} tag
        return self.request.headers.get("Plain-HX-Fragment", "")

    def get_htmx_action_name(self) -> str:
        return self.request.headers.get("Plain-HX-Action", "")
