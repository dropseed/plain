# plain-tunnel changelog

## [0.10.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.10.0) (2026-02-25)

### What's changed

- Added protocol version handshake — the client now sends a version query parameter and the server rejects incompatible clients with a clear error message ([a173676c0f3c](https://github.com/dropseed/plain/commit/a173676c0f3c))
- Fixed tunnel connection reliability with improved reconnection logic and exponential backoff ([4c09c9893528](https://github.com/dropseed/plain/commit/4c09c9893528))
- Replaced urllib with httpx for HTTP forwarding in the client ([4c09c9893528](https://github.com/dropseed/plain/commit/4c09c9893528))
- Simplified binary message parsing using struct-based framing instead of custom delimiters ([a9d11c51351b](https://github.com/dropseed/plain/commit/a9d11c51351b))
- Refactored client and server into cleaner request/response handling with dedicated `TunnelRequest` and `TunnelResponse` dataclasses ([4c09c9893528](https://github.com/dropseed/plain/commit/4c09c9893528))
- Renamed `PLAIN_DEV_TUNNEL_URL` environment variable to `DEV_TUNNEL_URL` ([6154e6ef8693](https://github.com/dropseed/plain/commit/6154e6ef8693))

### Upgrade instructions

- Rename `PLAIN_DEV_TUNNEL_URL` to `DEV_TUNNEL_URL` in your `.env` file.
- The tunnel server must be updated alongside the client due to the new protocol version handshake.

## [0.9.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.9.0) (2026-01-13)

### What's changed

- Improved README documentation with better structure, FAQs section, and clearer examples ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.8.2](https://github.com/dropseed/plain/releases/plain-tunnel@0.8.2) (2025-11-08)

### What's changed

- Fixed logger configuration to prevent propagation to root logger, avoiding duplicate log messages ([c714606](https://github.com/dropseed/plain/commit/c714606c85))

### Upgrade instructions

- No changes required

## [0.8.1](https://github.com/dropseed/plain/releases/plain-tunnel@0.8.1) (2025-11-03)

### What's changed

- Added command description to CLI for improved help text ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80103))

### Upgrade instructions

- No changes required

## [0.8.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.8.0) (2025-10-06)

### What's changed

- Added type annotations to all functions and methods for improved IDE/type checker support ([c87ca27](https://github.com/dropseed/plain/commit/c87ca27ed2))

### Upgrade instructions

- No changes required

## [0.7.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.7.0) (2025-09-22)

### What's changed

- Removed manual ALLOWED_HOSTS configuration documentation from README as it's now handled automatically by the Plain framework ([d3cb771](https://github.com/dropseed/plain/commit/d3cb7712b9))

### Upgrade instructions

- Changed ALLOWED_HOSTS default to `[]` with a deploy-only preflight check to ensure it's set in production environments

## [0.6.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.6.0) (2025-09-19)

### What's changed

- Updated minimum Python version requirement from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Enhanced README documentation with improved structure, table of contents, and detailed usage examples ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Added proper project description to pyproject.toml ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- Update your Python environment to Python 3.13 or higher

## [0.5.5](https://github.com/dropseed/plain/releases/plain-tunnel@0.5.5) (2025-07-07)

### What's changed

- No user-facing changes. Internal code cleanup and Biome linter fixes in the Cloudflare worker implementation ([3265f5f](https://github.com/dropseed/plain/commit/3265f5f), [9327384](https://github.com/dropseed/plain/commit/9327384)).

### Upgrade instructions

- No changes required
