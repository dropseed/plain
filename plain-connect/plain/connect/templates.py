from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from jinja2.runtime import Context
from opentelemetry import trace

from plain.runtime import settings
from plain.templates import register_template_extension, register_template_global
from plain.templates.jinja.extensions import InclusionTagExtension

from .identity import encrypt_identity, sign_render_token

if TYPE_CHECKING:
    from plain.http import Request

# plain.connect doesn't depend on plain.auth — an app without auth installed
# falls back to a no-op so callers don't need to special-case the absence.
try:
    from plain.auth import get_request_user
except ImportError:

    def get_request_user(request: Request) -> Any:
        return None


@register_template_extension
class ConnectPageviewsExtension(InclusionTagExtension):
    tags = {"connect_pageviews"}
    template_name = "connect/pageviews.html"

    def get_context(
        self, context: Context, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        request = context.get("request")
        token = settings.CONNECT_PAGEVIEWS_TOKEN
        secret = str(settings.CONNECT_SECRET_KEY) if token else ""
        return {
            "request": request,
            "connect_pageviews_token": token,
            "connect_pageviews_url": settings.CONNECT_PAGEVIEWS_URL,
            "connect_pageviews_identity": _identity_token(request, secret)
            if token
            else "",
            "connect_pageviews_trace_id": _current_trace_id() if token else "",
            "connect_pageviews_route": _current_route(request) if token else "",
        }


@register_template_extension
class ConnectSupportFieldsExtension(InclusionTagExtension):
    tags = {"connect_support_fields"}
    template_name = "connect/support_fields.html"

    def get_context(
        self, context: Context, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        secret = str(settings.CONNECT_SECRET_KEY)
        return {
            "connect_support_identity": _identity_token(context.get("request"), secret),
            "connect_support_render_token": sign_render_token(secret),
        }


@register_template_global
def connect_support_url(endpoint_id: str) -> str:
    """Build the form-action URL for a support endpoint."""
    base = settings.CONNECT_FORMS_URL.rstrip("/")
    return f"{base}/{quote(endpoint_id, safe='')}"


def _current_route(request: Request | None) -> str:
    # The matched URL route pattern (e.g. "/blog/<slug>/"), resolved before the
    # template renders. Lets pageviews aggregate by view instead of by raw URL.
    # Mirrors the http.route span attribute, including the leading slash.
    if request is None:
        return ""
    resolver_match = request.resolver_match
    if resolver_match is None or resolver_match.route is None:
        return ""
    return f"/{resolver_match.route}"


def _identity_token(request: Request | None, secret: str) -> str:
    if not secret or request is None:
        return ""
    user = get_request_user(request)
    if user is None:
        return ""
    return encrypt_identity(user.id, secret)


def _current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.trace_id:
        return ""
    return format(span_context.trace_id, "032x")
