from __future__ import annotations

import time
from multiprocessing.context import BaseContext


class WorkerHeartbeat:
    """Shared-memory heartbeat for spawn-based workers.

    Uses multiprocessing.Value (shared double) instead of tmpfile utime,
    since tmpfile-based heartbeats only work across fork (shared FDs).

    Relies on time.monotonic() being system-wide (CLOCK_MONOTONIC on
    Linux/macOS) so the arbiter and worker see the same clock.
    """

    def __init__(self, mp_context: BaseContext) -> None:
        # lock=False avoids the arbiter hanging if a worker is killed
        # while inside notify() (which would hold the lock). A torn
        # read is harmless here — worst case is a slightly stale
        # timestamp, which only affects heartbeat precision by microseconds.
        self._timestamp = mp_context.Value("d", time.monotonic(), lock=False)

    def notify(self) -> None:
        self._timestamp.value = time.monotonic()

    def last_update(self) -> float:
        return self._timestamp.value

    def close(self) -> None:
        # No-op: shared memory is cleaned up automatically.
        # Called from both the worker (entry.py) and arbiter (reap_workers);
        # safe to call multiple times.
        pass
