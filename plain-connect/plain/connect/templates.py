from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from plain.assets.urls import get_asset_url as _get_asset_url
from plain.html import Markup
from plain.runtime import settings

from .identity import encrypt_identity, sign_render_token
from .tracing import current_trace

if TYPE_CHECKING:
    from plain.http import Request

# plain.connect doesn't depend on plain.auth — an app without auth installed
# falls back to a no-op so callers don't need to special-case the absence.
try:
    from plain.auth import get_request_user
except ImportError:

    def get_request_user(request: Request) -> Any:
        return None


def connect_pageviews(request: Any) -> Markup:
    """Render the pageviews beacon `<script>` tag, or empty when disabled.

    Returned as `Markup` so a template can drop it in with `{{ ... }}`.
    """
    token = settings.CONNECT_PAGEVIEWS_TOKEN
    if not token:
        return Markup("")

    secret = str(settings.CONNECT_SECRET_KEY)
    return Markup(
        f'<script src="{_get_asset_url("connect/pageviews.js")}" '
        f'data-token="{token}" '
        f'data-pageviews-url="{settings.CONNECT_PAGEVIEWS_URL}" '
        f'data-identity="{_identity_token(request, secret)}" '
        f'data-trace-id="{current_trace().trace_id}" '
        f'data-route="{_current_route(request)}" '
        f'async nonce="{request.csp_nonce}"></script>'
    )


def connect_support_fields(request: Any) -> Markup:
    """Render the hidden identity / render-token inputs for a support form.

    Returned as `Markup` so a template can drop it inside its `<form>` with
    `{{ ... }}`.
    """
    secret = str(settings.CONNECT_SECRET_KEY)
    return Markup(
        f'<input type="hidden" name="plain_connect_render_token" '
        f'value="{sign_render_token(secret)}">'
        f'<input type="hidden" name="plain_connect_identity" '
        f'value="{_identity_token(request, secret)}">'
        '<input type="text" name="plain_connect_check" tabindex="-1" '
        'autocomplete="off" hidden aria-hidden="true">'
    )


def connect_support_url(endpoint_id: str) -> str:
    """Build the form-action URL for a support endpoint."""
    base = str(settings.CONNECT_CLOUD_URL).rstrip("/")
    return f"{base}/forms/{quote(endpoint_id, safe='')}"


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
