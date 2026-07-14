"""Tests for TunnelClient's public setup: how it derives the tunnel HTTP and
WebSocket URLs from the destination/subdomain/tunnel-host options a user
passes on the command line.
"""

from __future__ import annotations

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
