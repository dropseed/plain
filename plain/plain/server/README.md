# Server

**A production-ready HTTP server with HTTP/2 support, originally based on gunicorn.**

- [Overview](#overview)
- [Workers and threads](#workers-and-threads)
- [Configuration options](#configuration-options)
- [Settings](#settings)
- [Signals](#signals)
- [Memory leak detection](#memory-leak-detection)
- [FAQs](#faqs)
- [Architecture](#architecture)
- [Installation](#installation)

## Overview

You can run the built-in HTTP server with the `plain server` command.

```bash
plain server
```

By default, the server binds to `127.0.0.1:8000` with one worker process per CPU core and 4 threads per worker.

For local development, you can enable auto-reload to restart workers when code changes.

```bash
plain server --reload
```

In reload mode, a worker that fails to boot (an import error mid-edit, for example) doesn't shut the server down. It serves the traceback as a 500 response until the code changes again, then restarts with the new code. Without `--reload`, a boot failure stops the server immediately.

## Workers and threads

The server uses two levels of concurrency:

- **Workers** are separate OS processes. Each worker runs independently with its own memory. The default is `0` (auto), which spawns one worker per CPU core.
- **Threads** run inside each worker. Threads handle application code (middleware and views) using a thread pool. All network I/O (accepting connections, reading requests, writing responses, TLS, keepalive) is handled asynchronously on the event loop without consuming threads. The default is 4 threads per worker.

Total concurrent requests = `workers × threads`. On a 4-core machine with the defaults, that's `4 × 4 = 16` concurrent requests.

**When to adjust workers:** Workers provide true parallelism since each is a separate process with its own Python GIL. More workers means more memory usage but better CPU utilization. Use `--workers 0` (the default) to match your CPU cores, or set an explicit number.

**When to adjust threads:** Threads are used exclusively for running your application code (middleware and views). This means `SERVER_THREADS` directly controls how many views can execute in parallel — it's not shared with I/O operations. Increase threads if your views spend a lot of time waiting on I/O (database queries, external API calls). Decrease to 1 if you need to avoid thread-safety concerns.

**Long-lived connections:** Async views (SSE, WebSocket) run on the worker's event loop instead of occupying a thread pool slot. This means long-lived connections don't reduce your capacity for regular requests.

```bash
# Explicit worker count
plain server --workers 2

# More threads for I/O-heavy apps
plain server --threads 8

# Single-threaded workers (simplest, one request at a time per worker)
plain server --threads 1
```

## Configuration options

All options are available via the command line. Run `plain server --help` to see the full list.

Most options can also be configured via settings (see below). CLI arguments take priority over settings.

| Option                           | Setting             | Description                          |
| -------------------------------- | ------------------- | ------------------------------------ |
| `--bind` / `-b`                  | -                   | Address to bind (can repeat)         |
| `--workers` / `-w`               | `SERVER_WORKERS`    | Worker processes (0=auto, CPU count) |
| `--threads`                      | `SERVER_THREADS`    | Threads per worker                   |
| `--timeout` / `-t`               | `SERVER_TIMEOUT`    | Worker timeout in seconds            |
| `--access-log / --no-access-log` | `SERVER_ACCESS_LOG` | Enable/disable access logging        |
| `--reload`                       | -                   | Restart workers on code changes      |
| `--certfile`                     | -                   | Path to SSL certificate file         |
| `--keyfile`                      | -                   | Path to SSL key file                 |

## Settings

Server behavior can be configured in your `settings.py` file. These are the defaults:

```python
SERVER_WORKERS = 0  # 0 = auto (one per CPU core)
SERVER_THREADS = 4
SERVER_TIMEOUT = 30
SERVER_ACCESS_LOG = True
SERVER_ACCESS_LOG_FIELDS = [
    "method",
    "path",
    "query",
    "status",
    "duration_ms",
    "size",
    "ip",
    "user_agent",
    "referer",
]
SERVER_GRACEFUL_TIMEOUT = 30
SERVER_KEEPALIVE_TIMEOUT = 300  # idle connection timeout (h1 and h2)
SERVER_SENDFILE = True
SERVER_CONNECTIONS = 1000
SERVER_MAX_REQUESTS = 10000  # 0 = disabled, restart worker after N requests
SERVER_MAX_REQUESTS_JITTER = 1000  # random +/- variance to stagger restarts
```

`SERVER_KEEPALIVE_TIMEOUT` is how long an idle connection (no request in progress) stays open, for both HTTP/1.1 and HTTP/2 — in-flight requests are never affected. Keep it longer than your load balancer's connection reuse window so the balancer is always the side that closes idle connections; a server-side close races a request being written onto the connection (Heroku H13). Because idle pooled connections hold their slot for the whole window, size `SERVER_CONNECTIONS` above your balancer's total connection pool per server; a worker at the cap rejects new connections (and logs a warning).

Settings can also be set via environment variables with the `PLAIN_` prefix (e.g., `PLAIN_SERVER_WORKERS=4`).

The `WEB_CONCURRENCY` environment variable is supported as an alias for `SERVER_WORKERS`.

### Access log format

Access logs use the same `LOG_FORMAT` setting as the app logger, so they produce structured output in key-value or JSON format:

```
[INFO] Request method=GET path="/" status=200 duration_ms=12 size=1234 ip="127.0.0.1" user_agent="Mozilla/5.0..." referer="https://example.com"
```

See the [logs docs](../logs/README.md) for details on output formats.

### Access log fields

`SERVER_ACCESS_LOG_FIELDS` controls exactly which fields appear in access log entries. The default includes all common fields:

```python
# settings.py (default)
SERVER_ACCESS_LOG_FIELDS = [
    "method",
    "path",
    "query",
    "status",
    "duration_ms",
    "size",
    "ip",
    "user_agent",
    "referer",
]
```

Available fields: `method`, `path`, `url`, `query`, `status`, `duration_ms`, `size`, `ip`, `user_agent`, `referer`, `protocol`.

Use `url` for a combined path + query string (e.g., `url="/search?q=hello"`). Use `path` and `query` separately for production log aggregation.

In development, `plain dev` sets a minimal field list for cleaner output (`method`, `url`, `status`, `duration_ms`, `size`). Set `PLAIN_SERVER_ACCESS_LOG_FIELDS` in your environment to override.

### Per-response access log control

Individual responses can opt out of the access log by setting `log_access = False` on the response object. This is useful for noisy endpoints like health checks or asset serving.

```python
response = Response("ok")
response.log_access = False
return response
```

Plain uses this internally to suppress asset 304 responses (controlled by the `ASSETS_LOG_304` setting).

### How access logging works

Access logging has three layers, each at the right level of abstraction:

1. **`SERVER_ACCESS_LOG`** (server setting) — master switch that enables or disables access logging entirely.
2. **`response.log_access`** (per-response) — individual responses can opt out by setting `log_access = False`.
3. **`ASSETS_LOG_304`** (assets setting) — controls whether 304 Not Modified responses for assets are logged. When `False` (default), asset 304s set `log_access = False` on the response.

### Worker recycling

Long-running workers can accumulate memory from fragmentation, C extension leaks, or unbounded caches. By default, workers gracefully restart after 10000 requests (with +/- 1000 jitter) as a safety net — a genuinely leaky busy app still recycles every few hours, while a small app effectively never does.

When a worker reaches the limit, it stops accepting new connections and drains in-flight requests before exiting. The arbiter automatically spawns a replacement. The jitter prevents all workers from restarting at the same time in multi-worker deployments.

Both HTTP/1.1 requests and HTTP/2 streams count toward the limit. Set `SERVER_MAX_REQUESTS = 0` to disable recycling.

## Signals

The server responds to UNIX signals for process management.

| Signal    | Effect                                                 |
| --------- | ------------------------------------------------------ |
| `SIGTERM` | Graceful shutdown                                      |
| `SIGINT`  | Quick shutdown                                         |
| `SIGQUIT` | Quick shutdown                                         |
| `SIGUSR1` | Toggle memory recording (used by `plain memory leaks`) |

## Memory leak detection

```bash
plain memory leaks
plain memory leaks --duration 60
```

Records allocations on a running server using a three-phase approach:

1. Takes a baseline snapshot
2. Takes a midpoint snapshot after half the duration
3. Takes a final snapshot and compares both halves

Only allocations that grew in **both** halves are reported, filtering out one-time initialization. This makes it practical to run against production traffic — cache warmup and lazy loading won't show up as false positives.

The command auto-detects the running server and signals all workers via `SIGUSR1`. Use `--pid` to target a specific server if multiple are running. Recording auto-stops after 5 minutes if interrupted.

```
plain memory leaks --duration 30

Checking for leaks (30s, 2 worker(s))
Send traffic to your app while this runs.

  Phase 1/2 (15s)... done
  Phase 2/2 (15s)... done

  RSS: 98 MB → 99 MB (+1.2 MB)

Suspected leaks:
  app/views.py
    line 42: +18.6 KB → +19.1 KB
```

On Linux, RSS readings use `/proc/self/statm` for current (not peak) memory. On macOS, `ru_maxrss` (peak) is used as a fallback.

## FAQs

#### How do I run with SSL/TLS?

Provide both `--certfile` and `--keyfile` options pointing to your certificate and key files.

```bash
plain server --certfile cert.pem --keyfile key.pem
```

When TLS is enabled, the server automatically negotiates HTTP/2 with clients that support it via ALPN, while remaining compatible with HTTP/1.1 clients.

#### How do I run behind a reverse proxy?

Configure your proxy to pass the appropriate headers, then use these settings to tell Plain how to interpret them:

```python
# settings.py

# Tell Plain which header indicates HTTPS (format: "Header-Name: value")
HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"

# Trust X-Forwarded-Host, X-Forwarded-Port, X-Forwarded-For headers
HTTP_X_FORWARDED_HOST = True
HTTP_X_FORWARDED_PORT = True
HTTP_X_FORWARDED_FOR = True
```

See the [HTTP settings docs](../../http/README.md) for details on proxy header configuration.

#### How do I handle worker timeouts?

If workers are being killed due to timeouts, increase the timeout. This is common when handling long-running requests.

```python
# settings.py
SERVER_TIMEOUT = 120
```

Or via the CLI:

```bash
plain server --timeout 120
```

## Architecture

Plain's server is vertically integrated — there is no WSGI/ASGI boundary between the server and the framework. The server, handler, and middleware are all part of the same system.

### Request lifecycle

A request passes through three layers:

1. **Server** — accepts the connection, handles TLS, parses HTTP, manages keep-alive. All network I/O runs on an asyncio event loop. The server's job is protocol correctness and resource protection (connection limits, timeouts, body size limits).

2. **Handler** — dispatched in the thread pool, the handler orchestrates the application response. It runs the middleware chain, resolves the URL, and dispatches the view. The handler is a thin coordinator — it doesn't make policy decisions.

3. **Middleware** — application-level logic that wraps request processing. Security policies (CSRF, host validation), session management, database connection lifecycle, and response headers all live here. Middleware uses two phases: `before_request` (can short-circuit with a response) and `after_response` (can modify the response). See the [HTTP middleware docs](../http/README.md#middleware) for details on writing custom middleware.

```
Client
  │
  ▼
Server (event loop)
  ├── Accept connection
  ├── TLS handshake
  ├── Parse HTTP headers + body
  ├── Health check (responds directly, no thread pool)
  │
  ▼
Handler (thread pool)
  ├── before_request middleware chain
  │     ├── Host validation
  │     ├── HTTPS redirect
  │     ├── CSRF check
  │     ├── Session load
  │     └── [user middleware]
  ├── URL resolution → View dispatch
  └── after_response middleware chain (reverse)
        ├── [user middleware]
        ├── Session save
        ├── Slash redirect
        └── Default headers
  │
  ▼
Server (event loop)
  └── Write response
```

### Connection handling

Each worker process runs an asyncio event loop that handles all network I/O. A thread pool is reserved exclusively for application code.

```mermaid
graph TD
    A[Arbiter] -->|fork per core| W[Worker]
    W --> EL[asyncio event loop]
    EL -->|accept| C[Connection]
    C -->|wait readable| EL
    C -->|TLS handshake| TP_TLS[Thread pool]
    TP_TLS --> EL
    C -->|TLS ALPN| P{Protocol?}
    P -->|h2| H2[HTTP/2 handler]
    P -->|http/1.1| HDR[Read headers async]
    HDR --> PARSE[Parse request]
    PARSE --> SINK[Ingest body via BodySink]
    H2 -->|"h2 codec (sans-I/O)"| STREAMS[Multiplexed streams]
    STREAMS -->|DATA frames| SINK
    SINK -->|body complete| TP[Thread pool]
    TP --> MW[before_request + view + after_response]
    MW -->|write response async| EL
```

**Request body handling:** Both protocols receive the entire request body on the event loop before dispatch, through one ingestion path (the body sink): bodies stay in memory up to `SERVER_BODY_MAX_MEMORY_SIZE` (default 1MB) and spool to an anonymous temp file beyond it — the file is unlinked at creation, so a killed worker can never leak spooled disk (disk is a request-path dependency: a spool write failure is a 500 for that request, nothing more). Chunked transfer encoding is decoded during ingest, and the request is handed to the app de-chunked — a real `Content-Length`, no `Transfer-Encoding` — exactly as a buffering gateway would forward it, so `Content-Length` consumers like multipart parsing behave identically for chunked and declared bodies. Because the body is fully consumed off the wire before the response, connections keep-alive after uploads of any size, request threads are held only for view time, and async views can read bodies of any size.

This is the same model as Puma, Waitress, and PHP-FPM: views never stream a request body as it arrives — dispatch starts when the body is complete. Ingest happens before the request span opens, so its cost is recorded on the span as `http.request.body.size` and `plain.request.body_ingest_seconds` — check those before blaming a view for a slow upload.

**Request body limits:** Three independent bounds apply during ingest:

- `SERVER_MAX_REQUEST_BODY_SIZE` (default 10MB) — per-request policy cap, rejected with a 413. A declared Content-Length over the cap is refused from the headers, before any of the body transfers (and before any `100 Continue`); bodies with no declared length are rejected the moment received bytes exceed it. This is a pre-auth allowance — what an anonymous client can make a worker receive before any app code runs — so the default covers forms, images, and documents. Raise it deliberately if the app accepts larger uploads; for genuinely large files, prefer uploading direct to object storage (presigned URLs) rather than through the app server. `None` means no per-request cap of its own — a single body is then still bounded by the in-flight budget below, answered with a 413.
- `SERVER_MAX_INFLIGHT_BODY_SIZE` (default 1GB, `None` = unlimited) — worker-wide budget on total in-flight body bytes (memory + disk) across all connections, rejected with a 503 (with `Retry-After: 1` — this is load shedding, and the shed request is safe to retry). This bounds worst-case disk use under an upload flood; completed requests release their share.
- `SERVER_BODY_MIN_BYTES_PER_SECOND` (default 240, `0` = disabled) — minimum transfer rate while a request body is being received, after a short grace period and sustained over a rolling window (bytes sent early can't bank unbounded credit toward later silence). Inactivity timeouts can't stop a slow-drip body (R.U.D.Y.); the throughput floor can — on HTTP/1.1 against active socket-wait time, on HTTP/2 per stream. Violations get a 408.

## Installation

The server module is included with Plain. No additional installation is required.
