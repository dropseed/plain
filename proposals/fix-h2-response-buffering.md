---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-h2-body-buffering
---

# Fix: H2 non-streaming responses fully buffered before send (Finding 12)

## Status: UNRESOLVED

## Problem

For non-streaming, non-file HTTP/2 responses, `_async_write_h2_response()` materializes the entire body into memory via `_collect_body()` which does `b"".join(parts)` before sending any frames. This creates a temporary copy of the full response body.

**Key code location:** `plain/plain/server/http/h2handler.py:616-654`

```python
def _collect_body() -> bytes:
    parts: list[bytes] = []
    for chunk in http_response:
        if chunk:
            parts.append(chunk)
    return b"".join(parts)

body = await loop.run_in_executor(executor, _collect_body)
```

## Analysis

The impact is low for most responses. Typical HTML/JSON responses are small (< 100KB). The buffering only becomes a problem when:

1. A view returns a large non-streaming response (e.g., a multi-MB JSON export)
2. Many such responses are concurrent across H2 streams (compounds with Finding 1)

The reason for buffering is that HTTP/2 needs a `content-length` header for non-chunked responses, and the code adds one when not already present (lines 638-639). Without knowing the total size upfront, it must collect everything first.

## Proposed Fix

When the response already has a `Content-Length` header (the common case -- Plain's `Response` class sets it), stream the body in chunks rather than collecting it. Only fall back to full buffering when `Content-Length` is absent.

### Changes

**`plain/plain/server/http/h2handler.py`** - Modify the non-streaming branch (line 616+):

```python
else:
    # Check if Content-Length is already set
    has_content_length = any(
        n == "content-length" for n, _ in response_headers
    )

    if has_content_length:
        # Stream chunks directly -- no need to buffer
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()
            h2_resp.headers_sent = True

        # Iterate response in executor (response.__iter__ may do I/O)
        response_iter = iter(http_response)
        while True:
            chunk = await loop.run_in_executor(executor, next, response_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    else:
        # No Content-Length -- must buffer to determine size
        def _collect_body() -> bytes:
            parts: list[bytes] = []
            for chunk in http_response:
                if chunk:
                    parts.append(chunk)
            return b"".join(parts)

        body = await loop.run_in_executor(executor, _collect_body)
        if body:
            response_headers.append(("content-length", str(len(body))))

        # ... rest of existing send logic ...
```

## Considerations

- This reuses the exact same pattern already used for `StreamingResponse` at lines 591-615, so the code paths are well-tested.
- Most `Response` objects set `Content-Length` automatically, so the streaming path would be the common case.
- The fallback buffering path remains for edge cases (e.g., middleware that strips Content-Length).
- This is a low-priority optimization. The practical impact is small unless the server handles many large non-streaming responses over H2.
