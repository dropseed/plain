"""Unit tests for the Client ID Metadata Document pieces below the HTTP contract.

The fetch is exercised through `httpx.MockTransport` with DNS resolution
stubbed to a public address, so the request that reaches the transport is
exactly the one production would send — pinned IP, Host header, SNI name.
"""

from __future__ import annotations

import ipaddress
import json
import socket

import httpx
import pytest
from plain.oauthserver import cimd
from plain.oauthserver.cimd import (
    ClientMetadataError,
    cache_ttl_seconds,
    fetch_metadata_document,
    is_client_id_url,
    is_public_address,
    resolve_public_address,
    validate_client_id_url,
    validate_metadata_document,
)

CLAUDE_URL = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_CODE_URL = "https://claude.ai/oauth/claude-code-client-metadata"

# Frozen from the live documents on 2026-09-03.
CLAUDE_DOCUMENT = {
    "client_id": CLAUDE_URL,
    "client_name": "Claude",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
    "grant_types": [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
    ],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}
CLAUDE_CODE_DOCUMENT = {
    "client_id": CLAUDE_CODE_URL,
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}
# ChatGPT's document only offers private_key_jwt, which we don't support.
CHATGPT_URL = "https://chatgpt.com/oauth/IbUR3zxyNQ16/client.json"
CHATGPT_DOCUMENT = {
    "client_id": CHATGPT_URL,
    "client_name": "ChatGPT",
    "redirect_uris": ["https://chatgpt.com/connector/oauth/IbUR3zxyNQ16"],
    "token_endpoint_auth_method": "private_key_jwt",
    "jwks_uri": "https://chatgpt.com/oauth/jwks.json",
}


class TestClientIdUrl:
    def test_detection(self):
        assert is_client_id_url(CLAUDE_URL)
        assert not is_client_id_url("a1b2c3d4e5f6")
        assert not is_client_id_url("http://example.com/client")

    @pytest.mark.parametrize(
        "url",
        [
            CLAUDE_URL,
            "https://example.com/client",
            "https://example.com:8443/oauth/client.json",
            "https://example.com/oauth-client-metadata.json",
        ],
    )
    def test_accepts(self, url):
        assert validate_client_id_url(url) == url

    @pytest.mark.parametrize(
        ("url", "reason"),
        [
            ("http://example.com/client", "https"),
            ("https://example.com", "path"),
            ("https://example.com/", "path"),
            ("https://example.com/a/../client", "dot segments"),
            ("https://example.com/a/%2e%2e/client", "dot segments"),
            ("https://example.com/./client", "dot segments"),
            ("https://user:pw@example.com/client", "credentials"),
            ("https://example.com/client#frag", "fragment"),
            ("https://example.com/client?x=1", "query"),
            ("https://93.184.216.34/client", "IP address"),
            ("https://[2606:4700::1111]/client", "IP address"),
            ("https://localhost/client", "public hostname"),
            ("https://app.localhost/client", "public hostname"),
            ("https://client.local/metadata", "public hostname"),
            ("https://client.internal/metadata", "public hostname"),
            ("https://intranet/client", "public hostname"),
            ("https://example.com/cli ent", "whitespace"),
            ("https://example.com/cli\\ent", "backslash"),
            ("https://example.com:99999/client", "port"),
            ("https://example.com/" + "x" * 2048, "too long"),
        ],
    )
    def test_rejects(self, url, reason):
        with pytest.raises(ClientMetadataError, match=reason):
            validate_client_id_url(url)


class TestPublicAddress:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.5.5",
            "192.168.1.1",
            "169.254.169.254",  # cloud metadata
            "100.64.0.1",  # carrier-grade NAT
            "0.0.0.0",
            "192.0.2.1",  # documentation
            "224.0.0.1",  # multicast
            "255.255.255.255",
            "::1",
            "::",
            "fc00::1",  # unique local
            "fe80::1",  # link local
            "ff02::1",  # multicast
            "::ffff:10.0.0.1",  # IPv4-mapped
            "2002:0a00:0001::",  # 6to4 wrapping 10.0.0.1
            "64:ff9b::a00:1",  # NAT64 wrapping 10.0.0.1
        ],
    )
    def test_blocked(self, address):
        assert not is_public_address(ipaddress.ip_address(address))

    @pytest.mark.parametrize(
        "address",
        [
            "93.184.216.34",
            "160.79.104.1",  # Claude's egress range
            "2606:4700::1111",
            "::ffff:93.184.216.34",
            "64:ff9b::5db8:d822",  # NAT64 wrapping 93.184.216.34
        ],
    )
    def test_allowed(self, address):
        assert is_public_address(ipaddress.ip_address(address))

    def test_resolution_requires_every_answer_public(self, monkeypatch):
        def fake_getaddrinfo(host, port, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(ClientMetadataError, match="public address"):
            resolve_public_address(host="example.com", port=443)

    def test_resolution_returns_first_address(self, monkeypatch):
        def fake_getaddrinfo(host, port, **kwargs):
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:4700::1111", 443, 0, 0),
                ),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert resolve_public_address(host="example.com", port=443) == "2606:4700::1111"

    def test_resolution_failure(self, monkeypatch):
        def fake_getaddrinfo(host, port, **kwargs):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(ClientMetadataError, match="resolve"):
            resolve_public_address(host="example.com", port=443)


class TestCacheTtl:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("", 3600),
            ("public, max-age=60", 300),
            ("max-age=7200", 7200),
            ("max-age=999999", 86400),
            ("max-age=7200, s-maxage=600", 600),
            ("no-store", 3600),
            ("no-cache, max-age=7200", 3600),
            ("max-age=abc", 3600),
            ('max-age="900"', 900),
        ],
    )
    def test_ttl(self, header, expected):
        assert cache_ttl_seconds(header) == expected


def _json_response(document, **kwargs):
    headers = {"content-type": "application/json", **kwargs.pop("headers", {})}
    return httpx.Response(200, content=json.dumps(document).encode(), headers=headers)


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        cimd, "resolve_public_address", lambda *, host, port: "203.0.113.10"
    )


class TestFetch:
    def test_request_is_pinned_to_the_resolved_address(self, public_dns):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["host"] = request.headers["host"]
            seen["sni"] = request.extensions.get("sni_hostname")
            seen["accept"] = request.headers["accept"]
            return _json_response(
                CLAUDE_DOCUMENT, headers={"cache-control": "max-age=600"}
            )

        document, ttl = fetch_metadata_document(
            CLAUDE_URL, transport=httpx.MockTransport(handler)
        )
        assert document == CLAUDE_DOCUMENT
        assert ttl == 600
        assert seen["url"] == "https://203.0.113.10/oauth/mcp-oauth-client-metadata"
        assert seen["host"] == "claude.ai"
        assert seen["sni"] == "claude.ai"
        assert seen["accept"] == "application/json"

    def test_ipv6_address_is_bracketed(self, monkeypatch):
        monkeypatch.setattr(
            cimd, "resolve_public_address", lambda *, host, port: "2606:4700::1111"
        )
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return _json_response(CLAUDE_DOCUMENT)

        fetch_metadata_document(CLAUDE_URL, transport=httpx.MockTransport(handler))
        assert seen["url"].startswith("https://[2606:4700::1111]/")

    def test_non_default_port_is_kept(self, public_dns):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["host"] = request.headers["host"]
            return _json_response({**CLAUDE_DOCUMENT, "client_id": "x"})

        fetch_metadata_document(
            "https://example.com:8443/client", transport=httpx.MockTransport(handler)
        )
        assert seen["url"] == "https://203.0.113.10:8443/client"
        assert seen["host"] == "example.com:8443"

    @pytest.mark.parametrize(
        ("response", "reason"),
        [
            (httpx.Response(302, headers={"location": "https://elsewhere/"}), "302"),
            (httpx.Response(404), "404"),
            (httpx.Response(500), "500"),
            (
                httpx.Response(
                    200, content=b"{}", headers={"content-type": "text/html"}
                ),
                "not JSON",
            ),
            (
                httpx.Response(
                    200, content=b"{", headers={"content-type": "application/json"}
                ),
                "valid JSON",
            ),
            (
                httpx.Response(
                    200, content=b"[]", headers={"content-type": "application/json"}
                ),
                "JSON object",
            ),
            (
                httpx.Response(
                    200,
                    content=b"{" + b" " * 6000 + b"}",
                    headers={"content-type": "application/json"},
                ),
                "too large",
            ),
        ],
    )
    def test_rejected_responses(self, public_dns, response, reason):
        with pytest.raises(ClientMetadataError, match=reason):
            fetch_metadata_document(
                CLAUDE_URL, transport=httpx.MockTransport(lambda request: response)
            )

    def test_declared_length_over_cap_is_refused_before_reading(self, public_dns):
        def handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-length": "100000",
                },
                stream=httpx.ByteStream(b"{}"),
            )

        with pytest.raises(ClientMetadataError, match="too large"):
            fetch_metadata_document(CLAUDE_URL, transport=httpx.MockTransport(handler))

    def test_json_subtype_is_accepted(self, public_dns):
        def handler(request):
            return httpx.Response(
                200,
                content=json.dumps(CLAUDE_DOCUMENT).encode(),
                headers={
                    "content-type": "application/oauth-client+json; charset=utf-8"
                },
            )

        document, _ = fetch_metadata_document(
            CLAUDE_URL, transport=httpx.MockTransport(handler)
        )
        assert document["client_name"] == "Claude"

    def test_transport_errors_become_metadata_errors(self, public_dns):
        def handler(request):
            raise httpx.ConnectError("refused")

        with pytest.raises(ClientMetadataError, match="Could not fetch"):
            fetch_metadata_document(CLAUDE_URL, transport=httpx.MockTransport(handler))

    def test_timeout_becomes_metadata_error(self, public_dns):
        def handler(request):
            raise httpx.ReadTimeout("slow")

        with pytest.raises(ClientMetadataError, match="timed out"):
            fetch_metadata_document(CLAUDE_URL, transport=httpx.MockTransport(handler))

    def test_dns_check_runs_before_any_request(self, monkeypatch):
        def blocked(*, host, port):
            raise ClientMetadataError("claude.ai does not resolve to a public address")

        monkeypatch.setattr(cimd, "resolve_public_address", blocked)
        calls = []

        def handler(request):
            calls.append(request)
            return _json_response(CLAUDE_DOCUMENT)

        with pytest.raises(ClientMetadataError, match="public address"):
            fetch_metadata_document(CLAUDE_URL, transport=httpx.MockTransport(handler))
        assert calls == []


class TestDocumentValidation:
    def test_claude_document(self):
        metadata = validate_metadata_document(url=CLAUDE_URL, document=CLAUDE_DOCUMENT)
        assert metadata.name == "Claude"
        assert metadata.redirect_uris == ["https://claude.ai/api/mcp/auth_callback"]

    def test_claude_code_document_keeps_portless_loopback_uris(self):
        metadata = validate_metadata_document(
            url=CLAUDE_CODE_URL, document=CLAUDE_CODE_DOCUMENT
        )
        assert metadata.redirect_uris == [
            "http://localhost/callback",
            "http://127.0.0.1/callback",
        ]

    def test_chatgpt_document_is_rejected_for_private_key_jwt(self):
        with pytest.raises(ClientMetadataError, match="private_key_jwt"):
            validate_metadata_document(url=CHATGPT_URL, document=CHATGPT_DOCUMENT)

    def test_client_name_is_truncated(self):
        document = {**CLAUDE_DOCUMENT, "client_name": "x" * 300}
        assert (
            len(validate_metadata_document(url=CLAUDE_URL, document=document).name)
            == 255
        )

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            ({"client_id": "https://claude.ai/oauth/other"}, "does not match"),
            ({"client_id": CLAUDE_URL + "/"}, "does not match"),
            ({"client_name": ""}, "client_name"),
            ({"client_name": None}, "client_name"),
            ({"client_name": ["Claude"]}, "client_name"),
            ({"redirect_uris": []}, "redirect_uris"),
            ({"redirect_uris": "https://claude.ai/cb"}, "redirect_uris"),
            ({"redirect_uris": ["http://claude.ai/cb"]}, "HTTPS or loopback"),
            ({"redirect_uris": ["javascript:alert(1)"]}, "HTTPS or loopback"),
            (
                {"redirect_uris": ["https://claude.ai/cb https://evil/cb"]},
                "HTTPS or loopback",
            ),
            ({"redirect_uris": ["https://claude.ai/cb#frag"]}, "HTTPS or loopback"),
            ({"redirect_uris": ["https://claude.ai/" + "x" * 2000]}, "too long"),
            ({"token_endpoint_auth_method": "client_secret_basic"}, "not supported"),
            ({"client_secret": "shh"}, "client secret"),
            ({"client_secret_expires_at": 0}, "client secret"),
            ({"grant_types": ["refresh_token"]}, "authorization_code"),
            ({"grant_types": "authorization_code"}, "authorization_code"),
            ({"response_types": ["token"]}, "code"),
        ],
    )
    def test_rejects(self, changes, reason):
        document = {**CLAUDE_DOCUMENT, **changes}
        with pytest.raises(ClientMetadataError, match=reason):
            validate_metadata_document(url=CLAUDE_URL, document=document)

    def test_optional_fields_may_be_absent(self):
        document = {
            "client_id": CLAUDE_URL,
            "client_name": "Minimal",
            "redirect_uris": ["https://claude.ai/cb"],
        }
        metadata = validate_metadata_document(url=CLAUDE_URL, document=document)
        assert metadata.name == "Minimal"
