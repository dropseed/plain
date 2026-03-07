---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-h2-ingress-queue
- fix-h2-stream-concurrency
---

# Fix: HTTP/2 Request Bodies Fully Buffered in Memory Per Stream

## Status: UNRESOLVED

## Problem Summary

Each HTTP/2 stream accumulates its entire request body into an in-memory `BytesIO` object (`H2Stream.data`) before dispatching to application code. The per-stream size is capped at `DATA_UPLOAD_MAX_MEMORY_SIZE` (default 2.5 MB, with a 10 MiB fallback when the setting is `None`), but there is no aggregate memory budget across streams.

With N concurrent streams each buffering up to `max_body` bytes, total memory consumption can reach `N * max_body`. Combined with Finding 1 (unbounded stream concurrency), this creates a memory amplification vector.

### Code references

- `plain/plain/server/http/h2handler.py:40-49` -- `H2Stream` class with `self.data = io.BytesIO()` and `self.data_size = 0`
- `plain/plain/server/http/h2handler.py:380-419` -- `DataReceived` handler: each chunk is written to `stream.data.write(event.data)` with a per-stream size check against `max_body`, but no cross-stream budget
- `plain/plain/server/http/h2handler.py:215-216` -- After stream ends, `stream.data.seek(0)` and body is assigned to `http_request._stream`

### Comparison with HTTP/1.1

HTTP/1.1 has two paths (see `plain/plain/server/workers/thread.py:426-466`):

1. **Small bodies** (<= `max_body`): Pre-buffered in `_async_read_body`, then wrapped in a `BufferUnreader`. Similar to H2 but only one request at a time per connection.
2. **Large bodies** (> `max_body`): Use `AsyncBridgeUnreader` which streams data lazily from the socket -- body is never fully buffered in server memory.

HTTP/2 has **no equivalent of the bridge/streaming path**. All bodies are fully buffered regardless of size (up to `max_body`).

### Mitigating factors already present

- Per-stream size cap (`max_body`) with 413 response on overflow (lines 388-413)
- `acknowledge_received_data` is called properly for flow control (lines 405-406, 417-418)
- h2 library's default initial window size (65535 bytes) provides some natural throttling

### What remains unaddressed

- No aggregate memory budget across concurrent streams
- No disk spooling for large H2 bodies
- No streaming/incremental body consumption path for H2

## Proposed Fix

### Phase 1: Aggregate memory budget (recommended, low complexity)

Add a per-connection byte counter tracking total buffered body data across all active streams. When the aggregate exceeds a configurable limit, reject new streams with 503 or defer reading.

**File:** `plain/plain/server/http/h2handler.py`

1. Add to `H2ConnectionState.__init__` (line ~268):

```python
self.aggregate_body_size: int = 0
# Default: 4x max_body -- allows ~4 max-size uploads concurrently
self.max_aggregate_body: int = max_body * 4
```

2. Pass `max_body` into `H2ConnectionState` constructor (currently only used locally in the event loop).

3. In the `DataReceived` handler (line ~414-416), before writing data:

```python
elif state.aggregate_body_size + len(event.data) > state.max_aggregate_body:
    # Aggregate budget exceeded -- reject this stream
    try:
        conn.send_headers(event.stream_id, [(":status", "503"), ...])
        conn.send_data(event.stream_id, b"<h1>503 Service Unavailable</h1>", end_stream=True)
    except h2.exceptions.ProtocolError:
        ...
    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    state.streams.pop(event.stream_id, None)
else:
    stream.data_size += len(event.data)
    state.aggregate_body_size += len(event.data)
    stream.data.write(event.data)
    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
```

4. In `cleanup_stream` or when a stream is popped from `state.streams`, subtract the stream's `data_size` from `aggregate_body_size`.

### Phase 2: Disk spooling (future, higher complexity)

Replace `io.BytesIO` with `tempfile.SpooledTemporaryFile(max_size=spool_threshold)` so bodies exceeding a threshold spill to disk automatically. This would bring H2 closer to parity with HTTP/1.1's bridge path for large uploads.

This is lower priority because:

- Most H2 traffic is browser-originated (small JSON/form bodies)
- Large file uploads typically use HTTP/1.1 or multipart with streaming
- Phase 1's aggregate budget already bounds total memory

## Settings to Add

| Setting                 | Default | Purpose                                                   |
| ----------------------- | ------- | --------------------------------------------------------- |
| None needed for Phase 1 | --      | Use `DATA_UPLOAD_MAX_MEMORY_SIZE * 4` as aggregate budget |

A dedicated setting (e.g., `H2_MAX_AGGREGATE_BODY_SIZE`) could be added later if operators need independent control.

## Trade-offs

- Phase 1 adds minimal complexity (one counter + one check) and bounds worst-case memory
- The multiplier (4x) is a heuristic -- too low rejects legitimate concurrent uploads, too high doesn't bound memory effectively
- Phase 2 (disk spooling) changes the body interface and needs careful integration with Plain's multipart parser
- Neither phase adds true incremental/streaming body consumption for H2, which would require a fundamentally different architecture (per-stream async queues feeding the app)
