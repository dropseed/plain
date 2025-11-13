from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plain.http import Response
from plain.utils.cache import patch_vary_headers

from .templates import render_template_fragment


class HTMXViewMixin:
    """Mixin for View classes to add HTMX-specific functionality."""

    def render_template(self) -> str:
        # These methods are provided by the View base class
        template = self.get_template()  # type: ignore[attr-defined]
        context = self.get_template_context()  # type: ignore[attr-defined]

        if self.is_htmx_request() and self.get_htmx_fragment_name():
            return render_template_fragment(
                template=template._jinja_template,
                fragment_name=self.get_htmx_fragment_name(),
                context=context,
            )

        return template.render(context)

    def get_response(self) -> Response:
        response = super().get_response()  # type: ignore[misc]
        # Tell browser caching to also consider the fragment header,
        # not just the url/cookie.
        patch_vary_headers(
            response, ["HX-Request", "Plain-HX-Fragment", "Plain-HX-Action"]
        )
        return response

    def get_request_handler(self) -> Callable[..., Any]:
        if self.is_htmx_request():
            # You can use an htmx_{method} method on views
            # (or htmx_{method}_{action} for specific actions)
            method = f"htmx_{self.request.method.lower()}"  # type: ignore[attr-defined]

            if action := self.get_htmx_action_name():
                # If an action is specified, we throw an error if
                # the associated method isn't found
                return getattr(self, f"{method}_{action}")

            if handler := getattr(self, method, None):
                # If it's just an htmx post, for example,
                # we can use a custom method or we can let it fall back
                # to a regular post method if it's not found
                return handler

        return super().get_request_handler()  # type: ignore[misc]

    def is_htmx_request(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"  # type: ignore[attr-defined]

    def get_htmx_fragment_name(self) -> str:
        # A custom header that we pass with the {% htmxfragment %} tag
        return self.request.headers.get("Plain-HX-Fragment", "")  # type: ignore[attr-defined]

    def get_htmx_action_name(self) -> str:
        return self.request.headers.get("Plain-HX-Action", "")  # type: ignore[attr-defined]
