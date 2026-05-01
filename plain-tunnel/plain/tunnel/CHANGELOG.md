# plain-tunnel changelog

## [0.12.5](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.5) (2026-05-01)

### What's changed

- **Backed off tunnel reconnects so two clients can't duel over the same subdomain.** The reconnect backoff now only resets to 1s after a connection has stayed up for at least 5 seconds; short-lived connections (e.g. another client claiming the same subdomain and immediately closing this one) keep escalating up to 30s instead of looping tightly at 1s. Also stopped forwarding the `host` header to proxied targets, which was bypassing the local server's host validation. ([85383178e43e](https://github.com/dropseed/plain/commit/85383178e43e))

### Upgrade instructions

- No changes required.

## [0.12.4](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.4) (2026-03-22)

### What's changed

- Added `account_id` to wrangler.toml for non-interactive deploys ([e97362f914f4](https://github.com/dropseed/plain/commit/e97362f914f4))

### Upgrade instructions

- No changes required.

## [0.12.3](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.3) (2026-03-10)

### What's changed

- Updated README to use renamed `DEV_URL` env var (was `PLAIN_DEV_URL`) ([4ce989e42ece](https://github.com/dropseed/plain/commit/4ce989e42ece))

### Upgrade instructions

- If you reference `$PLAIN_DEV_URL` in your tunnel configuration, rename it to `$DEV_URL`.

## [0.12.2](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.2) (2026-03-09)

### What's changed

- Set explicit 30-second timeout on the httpx client used for forwarding requests to the local dev server, matching the `SERVER_TIMEOUT` default and preventing requests from hanging indefinitely ([6acd42948fee](https://github.com/dropseed/plain/commit/6acd42948fee))

### Upgrade instructions

- No changes required.

## [0.12.1](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.1) (2026-03-06)

### What's changed

- Fixed duplicate `Host` header in WebSocket proxy — the client was manually setting `Host` after forwarding headers, but `websockets.connect` already derives it from the URL. This caused connection failures with some servers ([83d1143a24bd](https://github.com/dropseed/plain/commit/83d1143a24bd))

### Upgrade instructions

- No changes required.

## [0.12.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.12.0) (2026-03-06)

### What's changed

- **WebSocket proxy support** — the tunnel now proxies WebSocket connections between the browser and the local dev server. New `ws-open`, `ws-message`, and `ws-close` message types handle the full WebSocket lifecycle, including binary messages (base64-encoded) and message queuing during connection setup ([5d9cea8ff72f](https://github.com/dropseed/plain/commit/5d9cea8ff72f))
- **Improved WebSocket proxy reliability** — fixed header forwarding to skip hop-by-hop and WebSocket handshake headers, rewrites `Host` to match the local server, and properly cleans up proxied connections on tunnel disconnect ([b55306047384](https://github.com/dropseed/plain/commit/b55306047384), [e3a3fc5019ba](https://github.com/dropseed/plain/commit/e3a3fc5019ba))
- **Tunnel WebSocket endpoint moved** — the control WebSocket now connects to `/__tunnel__` path instead of the root, freeing the root path for WebSocket proxying ([5d9cea8ff72f](https://github.com/dropseed/plain/commit/5d9cea8ff72f))
- **Fixed stream-end on cancel** — `stream-end` is no longer sent when a stream is cancelled by the server, preventing spurious messages ([b55306047384](https://github.com/dropseed/plain/commit/b55306047384))
- **Styled error pages** — tunnel error responses now render as styled HTML pages when the browser accepts HTML ([5d9cea8ff72f](https://github.com/dropseed/plain/commit/5d9cea8ff72f))
- **Protocol version bumped to 3** — both client and server now require protocol version 3 due to the new WebSocket proxy message types ([5d9cea8ff72f](https://github.com/dropseed/plain/commit/5d9cea8ff72f))

### Upgrade instructions

- The tunnel server must be updated alongside the client due to the protocol version bump to v3.
- No application code changes required.

## [0.11.0](https://github.com/dropseed/plain/releases/plain-tunnel@0.11.0) (2026-03-06)

### What's changed

- **Streaming response support** — the tunnel now forwards `text/event-stream` responses as a live stream instead of buffering the entire response. The client detects SSE responses, sends `stream-start`/`stream-end` messages over the WebSocket, and streams body chunks incrementally. The server resolves the HTTP response immediately with a `ReadableStream` so the browser receives events in real time ([dfa436ff5df7](https://github.com/dropseed/plain/commit/dfa436ff5df7))
- **Stream cancellation** — when the browser disconnects from a streaming response, the server sends a `stream-cancel` message back to the client, which stops reading from the upstream response ([dfa436ff5df7](https://github.com/dropseed/plain/commit/dfa436ff5df7))
- **Local development support** — the tunnel client now detects `localhost`/`127.0.0.1` hosts and uses `ws://`/`http://` instead of `wss://`/`https://`, enabling local testing with `wrangler dev`. Added a server README documenting the local dev workflow ([dfa436ff5df7](https://github.com/dropseed/plain/commit/dfa436ff5df7))
- **Protocol version bumped to 2** — both client and server now require protocol version 2 due to the new streaming message types ([dfa436ff5df7](https://github.com/dropseed/plain/commit/dfa436ff5df7))

### Upgrade instructions

- The tunnel server must be updated alongside the client due to the protocol version bump to v2.
- No application code changes required.

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
