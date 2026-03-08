---
packages:
- plain.server
related:
- server-httptools
- server-middleware-boundary
---

# Server Performance Optimizations

Opportunities identified by benchmarking and auditing the hot path.

## High Impact

### 1. Cache `http_date()` with 1-second TTL

`plain/plain/server/util.py:141` — called per response, runs `time.time()` + `email.utils.formatdate()` every time. HTTP date only has 1-second resolution, so a simple integer-keyed cache eliminates this for all but ~1 request/second.

### 2. Reduce allocations in `send_headers()`

`plain/plain/server/http/response.py:301-309` — builds a list of f-strings, joins them, formats again with `"{}\\r\\n".format(...)`, then encodes to latin-1. Three allocation steps that could be one: build bytes directly with a `BytesIO` or pre-encoded chunks and a single `sendall`.

### 3. Cache `request.scheme`

`plain/plain/http/request.py:299-314` — `@property`, not `@cached_property`. Every access parses `settings.HTTPS_PROXY_HEADER` (splits on `:`, strips whitespace) and checks the header value. Should be `@cached_property`.

### 4. Stop re-allocating BytesIO in body readers

`plain/plain/server/http/body.py` — `ChunkedReader` and `LengthReader` create new `BytesIO()` on multiple read paths instead of reusing buffers.

## Medium Impact

### 5. OpenTelemetry fast path when tracing is off

`plain/plain/internal/handlers/base.py` — even with a no-op tracer, this creates dicts, calls `baggage.set_baggage()` twice, builds `build_absolute_uri()` for the span, and formats the span name. A fast-path check could skip all of this when no exporter is configured.

### 6. `lines.pop(0)` is O(n) in header parsing

`plain/plain/server/http/message.py:100` — popping from the front of a list shifts all remaining elements. Using an index counter or `collections.deque` would be O(1).

## Lower Impact (easy wins)

### 7. Cache `request.content_length`

`plain/plain/http/request.py:217-223` — parses `Content-Length` header string to int on every access. Could be `@cached_property`.

### 8. Pre-encode constant response headers

`plain/plain/server/http/response.py:188,293` — `self.version` (the `Server:` header value) is constant per worker process but gets formatted into an f-string on every response. Could be pre-encoded once at worker init.
