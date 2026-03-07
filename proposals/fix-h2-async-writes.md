---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-h2-reader-threads
---

# Fix: Move H2 socket writes to async I/O (Finding 7)

## Status: UNRESOLVED

## Problem

The H2 handler's `flush()` method uses `run_in_executor(self.executor, self.sock.sendall, outgoing)` where `self.executor` is the shared app thread pool (`tpool`). Every H2 frame write (headers, data, flow-control) consumes a thread pool slot, competing with sync view dispatch, TLS handshakes, and bridge-mode parsing.

HTTP/1.1 writes were already migrated to async I/O (`util.async_sendall` using `loop.sock_sendall`), so H2 is the remaining holdout.

**Key code locations:**

- `plain/plain/server/http/h2handler.py:279-284` - `H2ConnectionState.flush()` uses executor for sendall
- `plain/plain/server/http/h2handler.py:348` - connection preface sent via executor
- `plain/plain/server/http/h2handler.py:488` - GOAWAY frame sent via executor
- `plain/plain/server/http/h2handler.py:493` - graceful close via executor

By contrast, HTTP/1.1 uses `util.async_sendall()` at:

- `plain/plain/server/http/response.py:433,456,458,493` - all async, no executor

## Proposed Fix

Replace `loop.run_in_executor(executor, self.sock.sendall, outgoing)` with `util.async_sendall(self.sock, outgoing)` in the H2 handler. The socket is already non-blocking (set in `TConn.__init__` at `thread.py:208`).

### Changes

**`plain/plain/server/http/h2handler.py`**

1. Add import: `from ..util import async_sendall`

2. Change `H2ConnectionState.flush()` (line 279-284):

```python
async def flush(self) -> None:
    """Send any pending h2 data to the socket."""
    outgoing = self.conn.data_to_send()
    if outgoing:
        await async_sendall(self.sock, outgoing)
```

3. Change connection preface send (line 348):

```python
await async_sendall(sock, conn.data_to_send())
```

4. Change GOAWAY send (line 486-488):

```python
goaway_data = conn.data_to_send()
if goaway_data:
    await async_sendall(sock, goaway_data)
```

5. The graceful close at line 493 (`_graceful_close`) uses blocking recv/shutdown and should remain in the executor since it's a teardown operation with timeouts.

## Considerations

- The H2 socket has `settimeout(30)` set at line 320 for write timeouts. With async I/O, we'd rely on asyncio's event-loop-level timeout instead. The `_async_send_h2_data` function already has a 5-second flow-control timeout (line 693-696), but raw sendall would need wrapping in `asyncio.wait_for` if a write timeout is desired.
- SSL sockets are handled by `util.async_sendall` already (it has the SSLWantWrite/SSLWantRead retry logic).
- The `write_lock` (asyncio.Lock) already serializes frame writes, so removing the executor doesn't change concurrency semantics.
