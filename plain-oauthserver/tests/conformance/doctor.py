#!/usr/bin/env python3
"""Walk the OAuth discovery a remote MCP client runs, and report each step.

    uv run python tests/conformance/doctor.py https://myapp.com/mcp

Turns "the connector won't connect" into a precise failure point: it probes the
exact sequence Claude's custom connector follows — 401 challenge → protected
resource metadata → authorization server metadata → dynamic registration — and
prints which step breaks. Standard library only, so it runs anywhere.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

_OK = "\033[32m  ok \033[0m"
_FAIL = "\033[31mFAIL \033[0m"


def _check(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  [{_OK if ok else _FAIL}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def _post_json(url: str, payload: dict) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )


def main(mcp_url: str) -> int:
    print(f"Probing MCP server: {mcp_url}\n")
    passed = True

    # 1. Unauthenticated request must 401 with a WWW-Authenticate challenge.
    print("1. Unauthenticated request")
    challenge = ""
    try:
        urllib.request.urlopen(_post_json(mcp_url, {}), timeout=10)
        passed &= _check(False, "401 without a token", "got a success response")
    except urllib.error.HTTPError as e:
        passed &= _check(e.code == 401, "401 without a token", f"status {e.code}")
        challenge = e.headers.get("WWW-Authenticate", "")
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    passed &= _check(bool(match), "WWW-Authenticate names resource_metadata", challenge)
    if not match:
        return 0 if passed else 1

    # 2. Protected resource metadata must name an authorization server.
    print("\n2. Protected resource metadata (RFC 9728)")
    status, prm = _get_json(match.group(1))
    passed &= _check(status == 200, "metadata fetched", f"status {status}")
    auth_servers = prm.get("authorization_servers") or []
    passed &= _check(
        bool(auth_servers), "authorization_servers present", str(auth_servers)
    )
    if not auth_servers:
        return 0 if passed else 1

    # 3. Authorization server metadata (RFC 8414).
    print("\n3. Authorization server metadata (RFC 8414)")
    issuer = auth_servers[0].rstrip("/")
    status, meta = _get_json(f"{issuer}/.well-known/oauth-authorization-server")
    passed &= _check(status == 200, "metadata fetched", f"status {status}")
    for field in ("issuer", "authorization_endpoint", "token_endpoint"):
        passed &= _check(field in meta, f"{field} present")
    passed &= _check(
        meta.get("code_challenge_methods_supported") == ["S256"],
        "PKCE S256 advertised",
        str(meta.get("code_challenge_methods_supported")),
    )
    passed &= _check(
        "none" in (meta.get("token_endpoint_auth_methods_supported") or []),
        "public clients (auth method 'none') advertised",
    )
    reg = meta.get("registration_endpoint")
    passed &= _check(bool(reg), "registration_endpoint present (DCR)", str(reg))

    # 4. Dynamic client registration (RFC 7591).
    if reg:
        print("\n4. Dynamic client registration (RFC 7591)")
        try:
            req = _post_json(
                reg,
                {
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                    "token_endpoint_auth_method": "none",
                    "client_name": "oauth-doctor",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                registered = json.loads(resp.read())
                passed &= _check(
                    resp.status == 201,
                    "registration returns 201",
                    f"status {resp.status}",
                )
                passed &= _check(bool(registered.get("client_id")), "client_id issued")
        except urllib.error.HTTPError as e:
            passed &= _check(False, "registration returns 201", f"status {e.code}")

    print(
        "\n" + ("All checks passed." if passed else "Some checks FAILED — see above.")
    )
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or not urlparse(sys.argv[1]).scheme:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
