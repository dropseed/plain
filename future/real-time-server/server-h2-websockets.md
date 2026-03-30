---
branch: websockets-v2
related:
  - realtime-architecture
  - server-httptools
---

# plain-server: HTTP/2 WebSocket support (RFC 8441)

WebSocket currently works only over HTTP/1.1 (RFC 6455 Upgrade). When a browser has an existing HTTP/2 connection, it falls back to a separate HTTP/1.1 connection for WebSocket. RFC 8441 defines Extended CONNECT, allowing WebSocket streams to multiplex alongside regular HTTP/2 traffic on one connection.

## Difficulty: medium

The WebSocket protocol layer (`protocols/websocket.py`) and view API (`views/websocket.py`) don't change — they already work against `asyncio.StreamReader`/writer interfaces. All work is in the H2 handler.

## What needs to change

### 1. Enable Extended CONNECT in h2 config

One line in `h2.py`: set `enable_connect_protocol=True` on `H2Configuration`. This advertises `SETTINGS_ENABLE_CONNECT_PROTOCOL=1` to clients.

### 2. Detect WebSocket CONNECT in the H2 event loop

Currently all streams accumulate data and dispatch on `StreamEnded`. WebSocket streams via Extended CONNECT never end — they stay open for bidirectional data.

- On `RequestReceived`: detect `:method=CONNECT` + `:protocol=websocket`. Start a WebSocket stream task immediately (don't wait for `StreamEnded`).
- On `DataReceived` for a WebSocket stream: feed data into that stream's `asyncio.StreamReader` instead of accumulating in `H2Stream.data`.
- On `StreamEnded`/`StreamReset` for a WebSocket stream: signal the reader EOF.

### 3. Create H2-to-asyncio stream adapters (~60-80 lines)

`H2StreamReader`: Thin wrapper around `asyncio.StreamReader`. The H2 event loop calls `.feed_data()` on incoming `DataReceived` events and `.feed_eof()` on stream end.

`H2StreamWriter`: Adapter with `.write()` and `.drain()` that sends data as H2 DATA frames through the h2 connection, respecting flow control via `_async_send_h2_data()` and the write lock.

### 4. Wire up WebSocket lifecycle for H2 streams

New `_async_handle_websocket_stream()` function — similar to `_async_handle_stream()` but:

- Routes through the handler to get `WebSocketUpgradeResponse`
- Sends `200 OK` on the H2 stream (not 101 — that's HTTP/1.1 only)
- Creates adapter reader/writer, creates `WebSocketConnection`, runs lifecycle
- Ends the H2 stream on completion

### 5. Adjust WebSocketView.get() for H2

Currently checks `Upgrade: websocket` header (line 268). H2 WebSocket requests use `:protocol` instead — no `Upgrade` header. Either skip the check for HTTP/2 requests or have the H2 handler set a marker on the request.

## Testing

- No standardized test suite exists for HTTP/2 WebSockets specifically
- **Autobahn** (`tools/autobahn-wstest`) covers RFC 6455 framing compliance over HTTP/1.1 — framing is the same regardless of transport, so passing Autobahn means the framing layer is correct
- **h2spec** covers HTTP/2 protocol compliance but not Extended CONNECT
- Custom integration tests needed for: Extended CONNECT negotiation, WS frames inside H2 DATA frames, multiplexing WS + regular HTTP/2 on one connection

## Prerequisites (done)

Asyncio-native TLS is already implemented — `asyncio.start_server(ssl=...)` handles accept + TLS, giving all connections `asyncio.StreamReader`/`StreamWriter` from the start. The WebSocket handler receives the same reader/writer used for HTTP. TLS is invisible. No thread bridge needed.
