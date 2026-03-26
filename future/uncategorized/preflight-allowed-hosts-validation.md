# plain-preflight: ALLOWED_HOSTS Pattern Validation

- Add preflight check to validate `ALLOWED_HOSTS` patterns are correctly formatted
- Catch common misconfigurations that silently fail to match legitimate traffic
- Check runs at startup and in deployment preflight to catch issues early

## Patterns to Check

- `"*"` anywhere in pattern → suggest `.example.com` for subdomains or `[]` for dev
- Patterns starting with protocol (`http://`, `https://`) → suggest domain only
- Patterns with ports (`example.com:8000`) → warn ports are stripped during validation
- Invalid CIDR notation (e.g., `192.168.1.0/33`) → validate with `ipaddress.ip_network()`

## Context

- The `"*"` pattern was removed in plain@0.67.0 (commit d3cb7712b9) but not documented in CHANGELOG
- Breaking change: `ALLOWED_HOSTS = ["*"]` silently stops working and blocks all traffic
- Users may still have `["*"]` in configs since the change wasn't clearly communicated
- Replacement: use `[]` (empty list) for dev, or specify actual domains for production

## Why It Matters

- `*.example.com` looks like valid wildcard notation but matches **nothing** (correct: `.example.com`)
- `"*"` anywhere in pattern matches nothing (no longer supported as of 0.67.0)
- Invalid CIDR blocks legitimate IPs without clear error message
- Ports in patterns won't work as expected since `request.host` has port stripped
- These misconfigurations block legitimate traffic, which is a serious production issue
- Better to fail fast at startup than discover in production when requests are rejected
