from __future__ import annotations

from typing import Any

from jinja2.runtime import Context
from opentelemetry import trace

from plain.runtime import settings
from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension

from .identity import encrypt_identity


@register_template_extension
class ConnectPageviewsExtension(InclusionTagExtension):
    tags = {"connect_pageviews"}
    template_name = "connect/pageviews.html"

    def get_context(
        self, context: Context, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        request = context.get("request")
        token = settings.CONNECT_PAGEVIEWS_TOKEN
        return {
            "request": request,
            "connect_pageviews_token": token,
            "connect_pageviews_url": settings.CONNECT_PAGEVIEWS_URL,
            "connect_pageviews_identity": _identity_token(request) if token else "",
            "connect_pageviews_trace_id": _current_trace_id() if token else "",
            "connect_pageviews_route": _current_route(request) if token else "",
        }


def _current_route(request: Any) -> str:
    # The matched URL route pattern (e.g. "/blog/<slug>/"), resolved before the
    # template renders. Lets pageviews aggregate by view instead of by raw URL.
    # Mirrors the http.route span attribute, including the leading slash.
    if request is None:
        return ""
    resolver_match = request.resolver_match
    if resolver_match is None or resolver_match.route is None:
        return ""
    return f"/{resolver_match.route}"


def _identity_token(request: Any) -> str:
    identity_key = str(settings.CONNECT_PAGEVIEWS_IDENTITY_KEY)
    if not identity_key or request is None:
        return ""

    # Plain stores the authenticated user off-request (keyed by the request
    # object), reachable only via plain.auth. plain.connect doesn't depend on
    # plain.auth, so an app without it simply has no identity to attribute.
    try:
        from plain.auth import get_request_user
    except ImportError:
        return ""

    user = get_request_user(request)
    if user is None:
        return ""
    return encrypt_identity(user.id, identity_key)


def _current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.trace_id:
        return ""
    return format(span_context.trace_id, "032x")
