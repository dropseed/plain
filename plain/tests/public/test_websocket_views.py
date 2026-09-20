"""The upgrade through the request pipeline, as `plain.test.Client` sees it.

What a view author can rely on: a well-formed handshake to a view with
`websocket()` yields the 101 (with the accept key and the negotiated
subprotocol), everything else on that URL behaves as before, auth and the
cross-origin rule apply before the socket exists, and middleware still
gets its say on the response.
"""

from __future__ import annotations

import pytest
from middleware_helpers import fresh_client
from plain.runtime import settings
from plain.test import Client
from plain.views import View
from websocket_helpers import upgrade_headers


def test_upgrade_yields_101_with_the_negotiated_subprotocol() -> None:
    response = Client().get(
        "/websocket/echo", headers=upgrade_headers(protocols="binary, echo")
    )
    assert response.status_code == 101
    assert response.headers["Sec-WebSocket-Protocol"] == "binary"


def test_unsupported_subprotocol_is_not_echoed() -> None:
    response = Client().get("/websocket/echo", headers=upgrade_headers(protocols="rfb"))
    assert response.status_code == 101
    assert "Sec-WebSocket-Protocol" not in response.headers


def test_plain_get_still_serves_the_page() -> None:
    response = Client().get("/websocket/echo")
    assert response.status_code == 200
    assert response.content == b"websocket page"


def test_plain_get_to_a_socket_only_view_is_405_without_leaking_the_handler() -> None:
    response = Client().get("/websocket/raises")
    assert response.status_code == 405
    assert response.headers["Allow"] == "OPTIONS"


@pytest.mark.parametrize(
    "missing",
    ["Upgrade", "Connection", "Sec-WebSocket-Version", "Sec-WebSocket-Key"],
)
def test_incomplete_handshake_is_served_as_a_get(missing: str) -> None:
    headers = upgrade_headers()
    del headers[missing]
    response = Client().get("/websocket/echo", headers=headers)
    assert response.status_code == 200


def test_before_request_rejection_wins_over_the_upgrade() -> None:
    response = Client().get("/websocket/forbidden", headers=upgrade_headers())
    assert response.status_code == 403


def test_cross_site_fetch_metadata_is_refused() -> None:
    response = Client().get(
        "/websocket/echo",
        headers=upgrade_headers(extra={"Sec-Fetch-Site": "cross-site"}),
    )
    assert response.status_code == 403


def test_foreign_origin_without_fetch_metadata_is_refused() -> None:
    response = Client().get(
        "/websocket/echo",
        headers=upgrade_headers(extra={"Origin": "https://evil.example"}),
    )
    assert response.status_code == 403


def test_same_origin_fetch_metadata_is_accepted_whatever_the_host_says() -> None:
    # The tunnel case: the browser's Origin is the public hostname, the
    # local Host is not — Sec-Fetch-Site settles it.
    response = Client().get(
        "/websocket/echo",
        headers=upgrade_headers(
            extra={
                "Origin": "https://myapp.plaintunnel.com",
                "Sec-Fetch-Site": "same-origin",
            }
        ),
    )
    assert response.status_code == 101


def test_trusted_origin_is_accepted() -> None:
    original = settings.CSRF_TRUSTED_ORIGINS
    settings.CSRF_TRUSTED_ORIGINS = ["https://partner.example"]
    try:
        response = Client().get(
            "/websocket/echo",
            headers=upgrade_headers(extra={"Origin": "https://partner.example"}),
        )
        assert response.status_code == 101
    finally:
        settings.CSRF_TRUSTED_ORIGINS = original


def test_matching_origin_is_accepted() -> None:
    response = Client().get(
        "/websocket/echo",
        headers=upgrade_headers(extra={"Origin": "https://testserver"}),
    )
    assert response.status_code == 101


def test_non_browser_client_without_origin_is_accepted() -> None:
    assert Client().get("/websocket/echo", headers=upgrade_headers()).status_code == 101


def test_after_response_middleware_runs_on_the_101() -> None:
    original = settings.MIDDLEWARE
    settings.MIDDLEWARE = ["middleware_helpers.StampingMiddleware"]
    try:
        response = fresh_client().get("/websocket/echo", headers=upgrade_headers())
        assert response.status_code == 101
        assert response.headers["X-Stamped"] == "yes"
        assert response.cookies["stamped"].value == "1"
    finally:
        settings.MIDDLEWARE = original


def test_a_sync_websocket_handler_is_rejected_at_class_definition() -> None:
    with pytest.raises(TypeError, match="must be `async def`"):

        class Wrong(View):
            def websocket(self, ws):  # type: ignore[override]
                pass
