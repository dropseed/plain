from __future__ import annotations

from typing import Any

from opentelemetry import trace

from plain.assets.urls import get_asset_url as _get_asset_url
from plain.html import Markup
from plain.runtime import settings

from .identity import encrypt_identity


def connect_pageviews(request: Any) -> Markup:
    """Render the pageviews beacon `<script>` tag, or empty when disabled.

    Returned as `Markup` so a template can drop it in with `{{ ... }}`.
    """
    token = settings.CONNECT_PAGEVIEWS_TOKEN
    if not token:
        return Markup("")

    return Markup(
        f'<script src="{_get_asset_url("connect/pageviews.js")}" '
        f'data-token="{token}" '
        f'data-pageviews-url="{settings.CONNECT_PAGEVIEWS_URL}" '
        f'data-identity="{_identity_token(request)}" '
        f'data-trace-id="{_current_trace_id()}" '
        f'async nonce="{request.csp_nonce}"></script>'
    )


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
