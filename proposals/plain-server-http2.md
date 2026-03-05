# plain (server): HTTP/2 Support

## Context

Gunicorn v25.0.0 (January 2026) added HTTP/2 support as a beta feature. Since Plain vendors Gunicorn's worker, this is now something we could adopt. The question is whether it's worth it, given that most deployments sit behind a reverse proxy that already terminates HTTP/2.

## Why it's more relevant than it seems

The typical argument against HTTP/2 at the app server level is that a reverse proxy (Nginx, Caddy, Cloudflare, ALB) handles it. That's true for most production deployments, but there are cases where it matters:

- **gRPC** — requires HTTP/2 end-to-end, can't be downgraded to HTTP/1.1 at the proxy
- **Stream multiplexing** — multiple SSE/streaming responses over a single connection, useful even behind a proxy (fewer internal connections)
- **Dev/staging simplicity** — Plain already does HTTPS in dev via `plain dev`, so HTTP/2 would work without needing a local proxy
- **Direct-to-internet deployments** — edge cases but they exist (container platforms, simple setups)

## Prerequisites: WSGI bypass ✅

WSGI is fundamentally HTTP/1.1 — it can't represent multiplexed streams. HTTP/2 support requires moving away from the WSGI interface between the server and the application.

**Done.** The server now bypasses WSGI entirely — `create_request()` builds a `PlainRequest` directly from parsed HTTP data and the worker calls `handler.get_response()` instead of going through WSGI's `environ`/`start_response`. See `thread.py:handle_request()`.

The server also migrated from `os.fork()` to `multiprocessing.spawn`, which simplifies the process model.

## Relationship to SSE/channels work

HTTP/2 and SSE/channels are **independent features** that were both blocked on WSGI bypass (now complete).

- **SSE/channels** needs direct socket control that doesn't fit the WSGI request/response model.
- **HTTP/2** needs multiplexed stream support that WSGI can't represent.

They complement each other: HTTP/2 multiplexing lets a browser hold an SSE connection and make regular requests over the **same TCP connection**, instead of tying up one of the browser's ~6 per-host HTTP/1.1 connections. Nice-to-have, not a requirement.

## Remaining prerequisites

1. **Upstream fixes** (see `plain-server-gunicorn-upstream-fixes.md`) — Lock-free PollableMethodQueue, thread pool exhaustion protection, request body discard. Reliability and performance first.

2. **HTTP/2 implementation** — With WSGI bypass complete, this is now unblocked. Main work is integrating the `h2` library with the thread worker's event loop.

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
