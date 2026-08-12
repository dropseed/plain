"""The classic-protocol compatibility branch: pre-2026-07-28 clients.

A classic client opens with `initialize`, sends no `params._meta` envelope
and none of the mirrored transport headers, and reads errors out of the body
at HTTP 200. claude.ai's connector proxy still speaks this protocol, which is
why the branch exists. Modern-path behavior is covered in test_http.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from plain.mcp.views import CLASSIC_PROTOCOL_VERSIONS
from plain.test import Client


def classic_post(
    path: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    msg_id: Any = 1,
    client: Client | None = None,
):
    """POST what a classic client sends: bare JSON-RPC, no envelope, no headers."""
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        body["id"] = msg_id
    if params is not None:
        body["params"] = params
    return (client or Client()).post(path, data=body, content_type="application/json")


class TestInitialize:
    def test_requested_version_is_echoed(self) -> None:
        response = classic_post(
            "/mcp",
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert result["capabilities"] == {"tools": {}}
        assert result["serverInfo"]["name"] == "public"

    def test_unknown_version_gets_newest_classic(self) -> None:
        # The classic negotiation rule: a version we don't serve — older,
        # newer, or absent — is answered with our newest classic revision,
        # and the client decides whether it can work with that.
        for params in ({"protocolVersion": "2024-11-05"}, {}):
            response = classic_post("/mcp", "initialize", params)
            result = response.json()["result"]
            assert result["protocolVersion"] == CLASSIC_PROTOCOL_VERSIONS[0]

    def test_no_session_is_issued(self) -> None:
        # Stateless in every revision: no session id means the client
        # proceeds sessionless, which the classic transport permits.
        response = classic_post("/mcp", "initialize", {"protocolVersion": "2025-06-18"})
        assert response.status_code == 200
        assert "Mcp-Session-Id" not in response.headers

    def test_modern_version_header_is_still_classic(self) -> None:
        # `initialize` doesn't exist in 2026-07-28, so whatever a client puts
        # in its headers, an initialize without the modern `_meta` envelope
        # is a classic handshake.
        response = Client().post(
            "/mcp",
            data={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            content_type="application/json",
            headers={"MCP-Protocol-Version": "2026-07-28"},
        )
        assert response.status_code == 200
        assert response.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_initialized_notification_is_accepted(self) -> None:
        # The handshake's second half is a notification — 202, no body, like
        # every other notification.
        response = classic_post("/mcp", "notifications/initialized", msg_id=None)
        assert response.status_code == 202
        assert not response.content


class TestClassicDispatch:
    def test_ping(self) -> None:
        response = classic_post("/mcp", "ping")
        assert response.status_code == 200
        assert response.json()["result"] == {}

    def test_tools_list_is_not_stamped(self) -> None:
        response = classic_post("/mcp", "tools/list")
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["tools"][0]["name"] == "Echo"
        # `resultType`, `serverInfo`, and the freshness hints are 2026-07-28
        # vocabulary — a classic client never asked for them.
        assert "resultType" not in result
        assert "_meta" not in result
        assert "ttlMs" not in result

    def test_tools_call(self) -> None:
        response = classic_post(
            "/mcp", "tools/call", {"name": "Echo", "arguments": {"text": "hi"}}
        )
        assert response.status_code == 200
        assert response.json()["result"]["content"][0]["text"] == "hi"

    def test_classic_version_header_still_routes_classic(self) -> None:
        # 2025-06-18 clients send their negotiated version in the header on
        # requests after `initialize` — only the `_meta` declaration selects
        # the modern path.
        response = Client().post(
            "/mcp",
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            content_type="application/json",
            headers={"MCP-Protocol-Version": "2025-06-18"},
        )
        assert response.status_code == 200
        assert "tools" in response.json()["result"]

    def test_unknown_method_error_rides_200_and_names_no_version(self) -> None:
        # The spec-mandated 404 for unknown methods is 2026-07-28 vocabulary;
        # a classic client reads the JSON-RPC error out of a 200 body. And
        # the error must not claim the server speaks only 2026-07-28 — this
        # client just negotiated a classic version it's happily using.
        response = classic_post("/mcp", "prompts/list")
        assert response.status_code == 200
        error = response.json()["error"]
        assert error["code"] == -32601
        assert "2026" not in error["message"]
        assert "data" not in error

    def test_invalid_params_error_rides_200(self) -> None:
        response = classic_post("/mcp", "tools/call", {})
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32602

    def test_handler_bug_is_an_internal_error(self) -> None:
        # A handler returning a non-dict is a server bug on either path — the
        # classic branch logs it and answers -32603 instead of shipping the
        # malformed result unstamped and unnoticed.
        response = classic_post("/rpc-boom", "bad")
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32603


class TestExtraTransportHeaders:
    """Headers a classic revision is silent about must not change the family.

    HTTP semantics make unrecognized headers fair game for any client, SDK,
    or middlebox, so their presence is not evidence of a revision. The live
    example is claude.ai's connector proxy: fully conformant 2025-11-25
    traffic (correct handshake, correct negotiated version header) that also
    sends `Mcp-Method` on every request. A classification that read that
    header as "modern" rejected it mid-session with a `_meta` error its
    revision never defined. Only the modern `_meta` declaration — or an
    `MCP-Protocol-Version` header naming `2026-07-28` itself — selects the
    modern ladder.
    """

    def test_claude_connector_shape_end_to_end(self) -> None:
        # The observed sequence: classic initialize (with the extra
        # Mcp-Method header), then tools/list under the negotiated version
        # header plus Mcp-Method, no `_meta` anywhere.
        response = Client().post(
            "/mcp",
            data={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-proxy", "version": "0"},
                },
            },
            content_type="application/json",
            headers={"Mcp-Method": "initialize"},
        )
        assert response.status_code == 200
        negotiated = response.json()["result"]["protocolVersion"]
        assert negotiated == "2025-11-25"

        response = Client().post(
            "/mcp",
            data={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            content_type="application/json",
            headers={
                "MCP-Protocol-Version": negotiated,
                "Mcp-Method": "tools/list",
            },
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["tools"][0]["name"] == "Echo"

    @pytest.mark.parametrize(
        "headers",
        [
            {"Mcp-Method": "tools/list"},
            {"MCP-Protocol-Version": "2026-01-01"},
            {"MCP-Protocol-Version": "2026-01-01", "Mcp-Method": "tools/list"},
        ],
        ids=["mcp-method-alone", "unknown-version", "both"],
    )
    def test_never_a_modern_error_without_meta(self, headers: dict[str, str]) -> None:
        # The invariant behind the class: a request that doesn't declare the
        # modern `_meta` (and doesn't name `2026-07-28` in its version
        # header) is never answered in modern vocabulary — no missing-_meta
        # -32602, no -32020 header mismatch, no -32022 unsupported version —
        # whatever extra headers it carries. It's a classic request, served
        # as one.
        response = Client().post(
            "/mcp",
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            content_type="application/json",
            headers=headers,
        )
        assert response.status_code == 200
        assert "tools" in response.json()["result"]


class TestClassicAuth:
    def test_initialize_still_requires_auth(self) -> None:
        # Auth runs in `before_request`, upstream of any protocol branching —
        # classic clients get the same 401 challenge modern ones do.
        response = classic_post(
            "/authed", "initialize", {"protocolVersion": "2025-06-18"}
        )
        assert response.status_code == 401
