"""Internal tests for TunnelClient's private response classification.

``_is_streaming_response`` is an implementation detail (it decides whether a
proxied response is forwarded as an SSE stream or a buffered body), so these
guard the internal behavior rather than a public contract.
"""

from __future__ import annotations

import httpx

from plain.tunnel.client import TunnelClient


def make_client(*, subdomain="myapp", tunnel_host="plaintunnel.com"):
    return TunnelClient(
        destination_url="http://localhost:8000",
        subdomain=subdomain,
        tunnel_host=tunnel_host,
        log_level="WARNING",
    )


def test_streaming_response_detected_by_content_type():
    client = make_client()

    sse = httpx.Response(200, headers={"content-type": "text/event-stream"})
    assert client._is_streaming_response(sse) is True


def test_non_streaming_response_is_not_flagged():
    client = make_client()

    for content_type in ("application/json", "text/html; charset=utf-8", ""):
        response = httpx.Response(200, headers={"content-type": content_type})
        assert client._is_streaming_response(response) is False
