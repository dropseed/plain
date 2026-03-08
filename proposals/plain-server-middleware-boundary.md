---
packages:
- plain.server
related:
- plain-server-direction
- plain-server-performance
---

# Move health check and Content-Length to server level

See [plain-server-direction.md](plain-server-direction.md) for the architectural principles behind these changes.

## Health check: move to server

`HealthcheckMiddleware` currently runs inside the thread pool, behind all before_request middleware. A health check under load has to wait for a thread pool slot, run through host validation and CSRF, then return `"ok"`.

Move it to the server's `_handle_connection` method, after header parsing but before thread pool dispatch. The server checks if the path matches `HEALTHCHECK_PATH` and responds directly with a 200 on the event loop.

This means:

- Health checks work even when the thread pool is fully saturated
- No middleware overhead (host validation, CSRF, default headers) on health check responses
- Load balancers and k8s probes get fast, reliable answers

### Implementation

1. Read `HEALTHCHECK_PATH` in worker `__init__` (alongside `max_body`, `max_connections`)
2. After `_async_read_headers`, check the request path against the health check path
3. If matched, write a minimal `200 OK` response directly via `util.async_write_error` (or similar) and continue to the next connection
4. Remove `HealthcheckMiddleware` from `BUILTIN_BEFORE_MIDDLEWARE`
5. Delete `plain/internal/middleware/healthcheck.py`

### H2 path

Also handle in `h2.py` — when a new stream's headers match the health check path, respond immediately without dispatching to the thread pool.

## Content-Length: move to response writer

`DefaultHeadersMiddleware` currently computes `Content-Length` for non-streaming responses. This is a transport concern — the server writes the bytes, it knows the length.

Move Content-Length computation to the response writer (`resp.async_write_response` for H1, the H2 send path for H2).

### Implementation

1. In `Response.async_write_response` (H1), compute and set `Content-Length` if not already present on non-streaming responses
2. In the H2 handler's response send path, same logic
3. Remove the Content-Length lines from `DefaultHeadersMiddleware`
4. `DefaultHeadersMiddleware` keeps its settings-based default headers logic

## Result

`BUILTIN_BEFORE_MIDDLEWARE` becomes:

```python
BUILTIN_BEFORE_MIDDLEWARE = [
    "plain.internal.middleware.headers.DefaultHeadersMiddleware",
    "plain.internal.middleware.hosts.HostValidationMiddleware",
    "plain.internal.middleware.https.HttpsRedirectMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
]
```

Health check is gone (server handles it). The list is cleaner but `DefaultHeadersMiddleware` still uses the ordering trick (first in before list so its after_response runs last). This is acceptable — it's a small list and the behavior is correct.
