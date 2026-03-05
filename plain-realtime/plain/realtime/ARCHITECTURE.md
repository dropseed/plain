# Realtime Architecture

This document records the design decisions behind Plain's realtime infrastructure. It exists so future maintainers understand _why_ things work this way, not just _how_.

## The core problem

Web applications need server-to-client push: notifications, live dashboards, streaming AI responses, chat. The question is how to add this to a sync Python framework without the complexity that Django Channels introduced.

## Key decisions

### SSE + HTTP POST as the primary pattern, not WebSockets

Most real-time use cases are server-to-client push (notifications, live updates, streaming responses). True bidirectional messaging (collaborative editing, multiplayer) is rare.

SSE handles server-to-client push with less ceremony than WebSockets:

- Works over regular HTTP (no upgrade handshake)
- Auth is just cookies/headers, same as any request
- Browser's `EventSource` API auto-reconnects
- Load balancers and proxies understand it natively

For the rare cases where the client needs to send data (chat messages, form input), a normal HTTP POST works. The server saves and calls `notify()`, and all SSE listeners receive the event. This "SSE for listening, POST for sending" pattern covers chat, dashboards, notifications, and AI agent streaming without WebSockets.

WebSocket support is included for cases that genuinely need high-frequency bidirectional messaging, but it's not the expected default path.

### Postgres LISTEN/NOTIFY as the event bus, not Redis

Plain is Postgres-exclusive. LISTEN/NOTIFY is a pub/sub system already running in the database:

- **No new infrastructure.** No Redis to deploy, configure, or monitor.
- **Transactional safety.** NOTIFY inside a transaction that rolls back is never sent. Redis pub/sub has no equivalent guarantee.
- **Simplicity.** Publishing an event is a SQL statement callable from views, jobs, signals, or database triggers.

The 8KB payload limit on `pg_notify` is fine for most events (type + ID). For larger data, the convention is: notify with a reference, client fetches full data via HTTP.

LISTEN/NOTIFY doesn't persist messages. If nobody's listening, the notification is gone. This is acceptable because:

- On reconnect, clients fetch current state via normal HTTP
- Chat-style "show me what I missed" queries the database directly
- SSE's `Last-Event-ID` can be used for catch-up if needed

### Background asyncio thread, not ASGI or a separate process

The server needs to hold SSE/WebSocket connections open cheaply. Each idle connection shouldn't consume a worker thread. Three approaches were considered:

**ASGI (Uvicorn/Daphne/Granian):** Would require wrapping the entire WSGI app in an ASGI adapter, or switching the whole framework to ASGI. That's restructuring how every HTTP request is served for the sake of one feature. Granian was specifically evaluated but only serves one interface — you can't mix WSGI and RSGI in the same process.

**Separate sidecar process:** Clean separation but adds deployment complexity. Doesn't work on platforms like Heroku that give you one port per dyno. Would require a reverse proxy to route SSE paths to the sidecar.

**Background asyncio thread in each worker:** The chosen approach. A daemon thread runs `asyncio.run_forever()`. Regular HTTP stays on the sync path (unchanged). Real-time connections get handed off to the async thread where they sit as cheap coroutines. One process, one port, works everywhere.

The async thread is small and contained — it manages connections, Postgres LISTEN subscriptions, heartbeats, and event dispatch. Application code never touches it.

### Sync SSEView API, not async

Django's approach to async was to make the entire stack async-capable: `async def` views, `aget()`/`afilter()` on querysets, `sync_to_async` wrappers everywhere. This created two parallel APIs, confused developers about which context they're in, and leaked complexity into every layer.

Plain takes a different position: **async is infrastructure, not a programming model.**

The `SSEView` class methods — `authorize()`, `subscribe()`, `transform()` — are all sync. They have full access to the ORM, sessions, and everything else. The framework calls them via `run_in_executor()` from the async thread when needed. Developers never write `async def`, never import `sync_to_async`, never think about which context they're in.

The async code exists only inside the framework's internal `handler.py` and `listener.py`. It's invisible to application code.

### WSGI bypass, not WSGI

The server and framework are in the same repository. WSGI is an interoperability standard between _different_ servers and _different_ frameworks. When you own both, the protocol boundary is overhead: the server packs HTTP data into a CGI-era `environ` dict, then the framework immediately unpacks it into a `Request` object.

Bypassing WSGI (the server builds `Request` directly and calls `handler.get_response()`) was a prerequisite for both channels and HTTP/2 support:

- Channels need direct socket control for the handoff to the async thread
- HTTP/2 needs multiplexed stream support that WSGI can't represent
- Both benefit from the server owning the socket lifecycle end-to-end

A WSGI compatibility adapter remains available for third-party server deployments.

### Socket handoff to the event loop

When the worker identifies a real-time request, it:

1. Runs `authorize()` and `subscribe()` in the sync middleware chain (full ORM access)
2. For WebSocket: the view returns a `WebSocketUpgradeResponse` marker; the worker sends the 101 Switching Protocols response, then wraps the socket in an `asyncio.StreamReader/Writer` pair
3. For SSE: the view returns an `AsyncStreamingResponse`; the worker writes chunks via the event loop
4. The connection is marked `handed_off = True` so the worker doesn't close the socket

The worker's `_handle_connection` tracks whether the socket was handed off. For WebSocket, `asyncio.create_connection(sock=conn.sock)` transfers socket ownership to the event loop's transport layer. For SSE, the async streaming response keeps the socket alive until the generator finishes.

### One Postgres connection per worker for LISTEN

Each worker's async thread maintains a single `psycopg.AsyncConnection` in autocommit mode. All channel subscriptions for all SSE/WebSocket clients on that worker are multiplexed over this one connection via LISTEN/UNLISTEN with reference counting.

This means 4 workers = 4 Postgres connections for real-time, regardless of how many clients are connected. The connection handles reconnection with exponential backoff and re-subscribes to all active channels on recovery.

## What was explicitly rejected

- **Django Channels' architecture:** Consumer class hierarchies, channel layers, Redis-backed group messaging. Too much framework surface area, and Python still isn't great at managing many concurrent connections.
- **Centrifugo/external pub/sub service:** Viable but adds infrastructure Plain doesn't need. Would require JWT token ceremony for auth instead of using existing session cookies.
- **Making everything async:** The Django lesson. Async should be contained infrastructure, not a programming model that infects every API.
- **Granian as the server:** Interesting technology (Rust I/O layer) but only serves one interface type per process. Can't mix sync HTTP and async real-time without wrapping everything in ASGI.
