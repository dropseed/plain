from __future__ import annotations

from collections.abc import Callable
from http import HTTPMethod
from typing import Any

from plain.html.views import TemplateView
from plain.http import Response
from plain.utils.cache import patch_vary_headers

__all__ = ["HTMXView"]


class HTMXView(TemplateView):
    """View with HTMX-specific functionality.

    Action handlers (`htmx_post_<action>` etc.) may return `None` to mean
    "re-render the current template (or active fragment)". Return an
    explicit `Response` only when the action diverges from a re-render —
    e.g. a redirect, a 204, or a custom payload.
    """

    def render_template(self) -> str:
        if self.is_htmx_request() and self.get_htmx_fragment_name():
            # The original `{% htmxfragment %}` mechanism was a Jinja
            # extension that walked the template's AST to find a named
            # fragment and render just that subtree. plain.html doesn't
            # have an equivalent yet — see the rip-out plan, step 6.
            # Templates that want fragment-style updates can hand-emit
            # the same wrapper div the tag used to produce.
            raise NotImplementedError(
                "HTMX fragment rendering ({% htmxfragment %}) is not yet "
                "implemented in plain.html. Hand-emit the "
                "<div plain-hx-fragment=... hx-target=this hx-swap=innerHTML ...> "
                "wrapper for now."
            )

        return self.get_template().render(self.get_template_context())

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
