# plain (server): HTTP/2 Support

## Context

Gunicorn v25.0.0 (January 2026) added HTTP/2 support as a beta feature. Since Plain vendors Gunicorn's worker, this is now something we could adopt. The question is whether it's worth it, given that most deployments sit behind a reverse proxy that already terminates HTTP/2.

## Why it's more relevant than it seems

The typical argument against HTTP/2 at the app server level is that a reverse proxy (Nginx, Caddy, Cloudflare, ALB) handles it. That's true for most production deployments, but there are cases where it matters:

- **gRPC** — requires HTTP/2 end-to-end, can't be downgraded to HTTP/1.1 at the proxy
- **Stream multiplexing** — multiple SSE/streaming responses over a single connection, useful even behind a proxy (fewer internal connections)
- **Dev/staging simplicity** — Plain already does HTTPS in dev via `plain dev`, so HTTP/2 would work without needing a local proxy
- **Direct-to-internet deployments** — edge cases but they exist (container platforms, simple setups)

## Prerequisites: WSGI bypass

WSGI is fundamentally HTTP/1.1 — it can't represent multiplexed streams. HTTP/2 support requires moving away from the WSGI interface between the server and the application.

This work is already in progress on the `claude/websocket-architecture-exploration-dTU2c` branch, which:

1. **Bypasses WSGI** — Both `SyncWorker` and `ThreadWorker` now construct a `PlainRequest` directly from parsed HTTP data (`create_plain_request()`) and call `handler.get_response()` instead of going through `self.wsgi(environ, resp.start_response)`.

2. **Adds per-worker async infrastructure** — A background asyncio event loop per worker process handles long-lived SSE connections. The `AsyncConnectionManager` manages socket handoff, heartbeats, and Postgres LISTEN/NOTIFY dispatch.

3. **Manages raw sockets** — SSE connections use `os.dup(client.fileno())` to hand sockets from the sync worker thread to the async loop. HTTP/2 stream multiplexing needs similar socket-level control.

These are the same architectural changes HTTP/2 would require. The channels/SSE work is building the foundation.

## Relationship to SSE/channels work

HTTP/2 and SSE/channels are **independent features** that share the same architectural prerequisite: getting off WSGI.

- **SSE/channels** needs WSGI bypass because long-lived connections with socket handoff don't fit the WSGI request/response model.
- **HTTP/2** needs WSGI bypass because WSGI can't represent multiplexed streams.

Neither depends on the other to function. SSE works fine over HTTP/1.1 (it always has — `EventSource` is an HTTP/1.1 feature). HTTP/2 is useful without SSE (request/response multiplexing, header compression).

They do complement each other: HTTP/2 multiplexing lets a browser hold an SSE connection and make regular requests over the **same TCP connection**, instead of tying up one of the browser's ~6 per-host HTTP/1.1 connections. Nice-to-have, not a requirement.

## Sequencing

1. **Upstream fixes** (see `plain-server-gunicorn-upstream-fixes.md`) — Lock-free PollableMethodQueue, thread pool exhaustion protection, request body discard. Reliability and performance first.

2. **WSGI bypass** (in progress on `claude/websocket-architecture-exploration-dTU2c`) — Drop WSGI as the internal interface. This is the big architectural shift that unblocks both SSE/channels and HTTP/2.

3. **SSE/channels and HTTP/2** (independent, either order) — Once WSGI is gone, these can be added independently. Channels/SSE is further along since it's being built alongside the WSGI bypass. HTTP/2 can follow whenever it's prioritized.

## Gunicorn's implementation

For reference, Gunicorn's HTTP/2 implementation:

- Uses the `h2` library as an optional dependency (`pip install gunicorn[http2]`)
- Requires SSL/TLS (HTTP/2 uses ALPN for protocol negotiation)
- Supports gthread (recommended), gevent, eventlet, and ASGI workers — not sync
- Configuration: `--http-protocols h2,h1` with fallback to HTTP/1.1
- Tunable: max concurrent streams, initial window size, max frame size, max header list size
- Does not implement Server Push (being deprecated even in browsers)
- h2spec compliant (146/146 RFC 7540 tests passing)

## Open questions

- How much of Gunicorn's HTTP/2 code can we reuse vs. needing to adapt for Plain's worker differences?
- Should HTTP/2 be on by default when SSL is enabled, or opt-in?
- Does the `h2` library work well with the background asyncio loop approach, or does it assume a different concurrency model?
- Priority relative to other server work (connection pooling, etc.)
