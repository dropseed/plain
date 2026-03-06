# plain-server: asyncio-native TLS

Move TLS handling from blocking `ssl.wrap_socket()` in `TConn.init()` to asyncio's SSL transport (`loop.start_tls()`), so the socket is never an `ssl.SSLSocket`.

## Motivation

- WebSocket over SSL currently requires a daemon thread per connection (a `_read_pump` thread + `_SSLSocketWriter`) because asyncio can't adopt an already-handshaked `ssl.SSLSocket` (Python 3.14+ explicitly rejects it)
- This is acceptable today because production TLS terminates at the reverse proxy — the app server sees plain TCP. The SSL path only runs in development (`uv run plain dev` uses HTTPS with a self-signed cert)
- But it's a known ceiling: SSL + WebSocket can't scale past ~hundreds of concurrent connections per worker due to thread overhead

## Current flow

```
sock_accept()                          # asyncio — raw TCP
→ _parse_request (thread pool):
    conn.init()                        # blocking ssl.wrap_socket() — socket becomes SSLSocket
    next(conn.parser)                  # blocking read from SSLSocket
→ _dispatch_async (event loop):
    response = WebSocketUpgradeResponse
    _create_ws_streams(ssl_socket)     # can't give SSLSocket to asyncio
      → spawn _read_pump thread        # workaround: blocking recv in thread
      → create _SSLSocketWriter        # workaround: blocking sendall via executor
```

## Proposed flow

```
sock_accept()                          # asyncio — raw TCP
→ _handle_connection:
    reader, writer = open_connection(sock=raw_sock)
    if SSL:
      start_tls(transport, ssl_context) # asyncio handles TLS at transport level
    → read HTTP headers (asyncio reader)
    → parse request
    → dispatch:
        sync view  → thread pool (gets parsed request, not the socket)
        async view → stays on event loop, reuses same reader/writer
        WebSocket  → reuses same reader/writer. No threads. Done.
```

## Key changes

### 1. TLS in `_handle_connection`, not `TConn.init()`

After `sock_accept()`, create asyncio reader/writer immediately. If SSL, use `loop.start_tls()` to layer TLS on the asyncio transport. The raw socket stays raw — asyncio's SSL transport handles encryption/decryption transparently.

### 2. HTTP parsing reads from asyncio streams

This is the load-bearing change. Currently `conn.parser` pulls bytes from the socket via blocking `recv()`. Two options:

**(a) Feed-based parser** — read bytes from asyncio reader, feed to parser:

```python
parser = RequestParser()
while not parser.complete:
    data = await reader.read(8192)
    parser.feed(data)
req = parser.result
```

**(b) Read-then-parse (more incremental)** — buffer on event loop until headers complete, then hand to existing parser in thread pool:

```python
raw = await read_until_double_crlf(reader)
req = await loop.run_in_executor(pool, parse_request, raw)
```

Option (b) minimizes parser changes. The existing gunicorn-derived parser would just need to accept a buffer instead of a socket.

### 3. `_create_ws_streams`, `_SSLSocketWriter`, `_read_pump` all deleted

WebSocket handler receives the same reader/writer used for HTTP. TLS is invisible.

### 4. Sync response writing through asyncio writer

Currently sync views write directly to the socket in the thread pool. Would need to go through the asyncio writer, or bridge back to blocking (same problem in reverse, just for writes — but writes are simpler since they're buffered).

## Ripple radius

| Area                  | Impact                                               |
| --------------------- | ---------------------------------------------------- |
| `TConn.init()`        | No longer does `ssl.wrap_socket()`                   |
| `_handle_connection`  | Owns TLS handshake + asyncio stream setup            |
| HTTP parsing          | Must accept fed bytes instead of pulling from socket |
| Sync response writing | Through asyncio writer or bridged                    |
| H2 connections        | Same treatment needed                                |
| Keepalive loop        | Already asyncio, minimal change                      |
| WebSocket             | Simplifies massively — thread bridge deleted         |
| SSE                   | Already asyncio, gets simpler                        |

## When to do this

Not now. The thread bridge works for its only real use case (dev server). This becomes worthwhile when:

- The HTTP parser is being replaced anyway (see `plain-server-httptools.md`) — a feed-based parser naturally supports this
- Connection-level improvements are needed (better slow-client handling, connection-level timeouts)
- The SSL + WebSocket ceiling becomes a real constraint (unlikely — production terminates TLS at proxy)

The parser change is the prerequisite. Everything else follows from it.
