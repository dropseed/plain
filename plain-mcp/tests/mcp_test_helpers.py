"""Shared request builders for the HTTP-level MCP tests.

Every 2026-07-28 request restates its protocol version and client
capabilities in `params._meta`, and mirrors its method (and target) into
headers. test_http.py, test_oauth.py and internal/test_observability.py all
need that envelope, so it's assembled once here.
"""

from __future__ import annotations

import json
from typing import Any

from plain.mcp import MCPView
from plain.mcp.views import (
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
)
from plain.test import Client


def _merge_headers(
    base: dict[str, str], overrides: dict[str, str | None] | None
) -> dict[str, str]:
    """Apply header overrides, where a `None` value drops the header entirely."""
    for key, value in (overrides or {}).items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def mcp_post(
    path: str,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    client: Client | None = None,
    headers: dict[str, str | None] | None = None,
):
    """POST a well-formed MCP request.

    Sends the body and the headers a real client would. `headers` overrides
    the mirrored headers, and a `None` value drops one — that's how the
    "header is missing" cases are written. Pass `client` to use a Client
    carrying auth or other defaults.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                META_PROTOCOL_VERSION: PROTOCOL_VERSION,
                META_CLIENT_CAPABILITIES: {},
            },
        },
    }

    request_headers = {
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    # The methods that name a target mirror it into Mcp-Name. Read the
    # mapping off the view so a new target-naming method doesn't need
    # this table copied here.
    if name_param := MCPView.name_header_params.get(method):
        request_headers["Mcp-Name"] = (params or {})[name_param]

    return (client or Client()).post(
        path,
        json_data=body,
        headers=_merge_headers(request_headers, headers),
    )


def mcp_post_raw(
    path: str,
    data: Any,
    *,
    method: str = "tools/list",
    client: Client | None = None,
    headers: dict[str, str | None] | None = None,
):
    """POST a body you built yourself.

    For the cases where the body *is* what's under test — a malformed
    envelope, a hand-built `_meta` — so `mcp_post`'s well-formed one can't be
    used. Sends only the two always-required headers, taking `method` for the
    `Mcp-Method` one, and overrides them the way `mcp_post` does. `data` is
    JSON-encoded when it's a dict and sent verbatim when it's a string, which
    is how the deliberately-unparseable bodies get through.
    """
    request_headers = {
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    return bare_post(
        path,
        data,
        client=client,
        headers=_merge_headers(request_headers, headers),
    )


def bare_post(
    path: str,
    data: Any,
    *,
    client: Client | None = None,
    headers: dict[str, str] | None = None,
):
    """POST bare JSON-RPC — no `_meta` envelope, only the headers given."""
    body = json.dumps(data) if isinstance(data, dict | list) else data
    return (client or Client()).post(
        path,
        body=body,
        content_type="application/json",
        headers=headers or {},
    )
