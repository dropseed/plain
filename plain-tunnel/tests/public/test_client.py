"""Tests for TunnelClient's pure setup logic: how it derives the tunnel
HTTP/WebSocket URLs from its options, and how it classifies responses.
"""

from __future__ import annotations

import httpx

from plain.tunnel.client import PROTOCOL_VERSION, TunnelClient


def make_client(*, subdomain="myapp", tunnel_host="plaintunnel.com"):
    return TunnelClient(
        destination_url="http://localhost:8000",
        subdomain=subdomain,
        tunnel_host=tunnel_host,
        log_level="WARNING",
    )


def test_remote_host_uses_secure_urls():
    client = make_client(subdomain="myapp", tunnel_host="plaintunnel.com")

    assert client.tunnel_http_url == "https://myapp.plaintunnel.com"
    assert client.tunnel_websocket_url == (
        f"wss://myapp.plaintunnel.com/__tunnel__?v={PROTOCOL_VERSION}"
    )


def test_localhost_uses_insecure_urls():
    client = make_client(subdomain="dev", tunnel_host="localhost:8443")

    assert client.tunnel_http_url == "http://dev.localhost:8443"
    assert client.tunnel_websocket_url == (
        f"ws://dev.localhost:8443/__tunnel__?v={PROTOCOL_VERSION}"
    )


def test_loopback_ip_uses_insecure_urls():
    client = make_client(subdomain="dev", tunnel_host="127.0.0.1:8000")

    assert client.tunnel_http_url.startswith("http://")
    assert client.tunnel_websocket_url.startswith("ws://")


def test_websocket_url_carries_protocol_version():
    client = make_client()
    assert client.tunnel_websocket_url.endswith(f"?v={PROTOCOL_VERSION}")


def test_streaming_response_detected_by_content_type():
    client = make_client()

    sse = httpx.Response(200, headers={"content-type": "text/event-stream"})
    assert client._is_streaming_response(sse) is True


def test_non_streaming_response_is_not_flagged():
    client = make_client()

    for content_type in ("application/json", "text/html; charset=utf-8", ""):
        response = httpx.Response(200, headers={"content-type": content_type})
        assert client._is_streaming_response(response) is False
