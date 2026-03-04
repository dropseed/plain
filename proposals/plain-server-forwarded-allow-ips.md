# Consolidate SERVER_FORWARDED_ALLOW_IPS with HTTPS_PROXY_HEADER

## Problem

There are two overlapping mechanisms for trusting proxy headers:

1. **`SERVER_FORWARDED_ALLOW_IPS`** (server layer, from gunicorn) — controls which client IPs are allowed to set `X-Forwarded-Proto`, `X-Forwarded-SSL`, and `X-Forwarded-Protocol` to determine the request scheme. Used in `plain/server/http/message.py` during HTTP parsing. Also gates `SCRIPT_NAME` and `PATH_INFO` forwarder headers.

2. **`HTTPS_PROXY_HEADER`** (framework layer) — a single `"Header-Name: value"` string that makes `request.is_https()` return True. Used in the request/response layer.

These do similar things at different levels. A user could configure one and not the other, leading to confusion (e.g., scheme detected as HTTPS at the server level but not at the framework level, or vice versa).

## Questions

- Should these be unified into a single setting?
- Is the server-level scheme detection even needed now that WSGI is gone? The server builds `Request` objects directly — could scheme detection happen entirely at the framework level?
- The `secure_scheme_headers` dict (`X-FORWARDED-PROTOCOL: ssl`, `X-FORWARDED-PROTO: https`, `X-FORWARDED-SSL: on`) is hardcoded on Config. Should users be able to customize which headers indicate HTTPS?
- The `forwarder_headers` list (`SCRIPT_NAME`, `PATH_INFO`) is also gated by `forwarded_allow_ips`. Is `SCRIPT_NAME` override still needed?
