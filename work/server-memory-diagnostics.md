---
labels:
  - plain.server
  - plain.cli
related:
  - observer-profiling
  - server-performance
---

# Server memory diagnostics

Server-side plumbing for memory diagnostics: `plain request --memory` for local debugging, and the shared-memory recording infrastructure that observer uses for production profiling.

## `plain request --memory`

`plain request` uses the test `Client` for in-process requests. Adding `--memory` wraps the request in `tracemalloc.start()` / `tracemalloc.stop()` and formats the diff. No server coordination needed.

`--repeat N` runs the request N times so per-request leaks accumulate and stand out against one-time initialization.

Output format (prototyped and validated):

```
plain request --memory /example-path --repeat 100

Response: 100 requests completed (all 200 OK)

Memory Profile:
  RSS: 87.2 MB → 89.1 MB (+1.9 MB)
  Tracked growth: +23.0 KB (266 objects)

Allocations by file:
  app/apis.py: +18.6 KB (+198 objects)
    line 92: +18.6 KB (+198 objects)
  app/processing/views.py: +3.6 KB (+66 objects)
    line 88: +3.6 KB (+66 objects)
```

Works locally, no production risk, no server changes. Ships as a single-file CLI change.

## Server recording plumbing

The infrastructure that allows observer (or any future profiling tool) to coordinate recordings across all server workers in production.

### Problem

The arbiter uses `multiprocessing.get_context("spawn")` — workers are independent processes. The only existing communication channels are `WorkerHeartbeat` (shared `multiprocessing.Value`) and signals (SIGTERM, SIGKILL, SIGABRT). No command channel exists.

### RecordingFlag (shared state)

Same pattern as `WorkerHeartbeat` — `multiprocessing.Value` instances created by the arbiter and passed to workers at spawn:

```python
class RecordingFlag:
    IDLE = 0
    PHASE_1 = 1  # started, baseline taken
    PHASE_2 = 2  # mid-point snapshot taken
    DONE = 3     # final snapshot, save results

    def __init__(self, mp_context):
        self._phase = mp_context.Value("i", self.IDLE, lock=False)
        self._nframe = mp_context.Value("i", 10, lock=False)
        self._duration = mp_context.Value("d", 60.0, lock=False)
        self._started_at = mp_context.Value("d", 0.0, lock=False)
```

Note: named `RecordingFlag` not `MemoryRecordingFlag` — this same mechanism could be reused for CPU profiling windows.

### Arbiter owns timing

Phase transitions in the existing 1s main loop. Workers react to whatever phase they see — idempotent transitions, no race conditions:

```python
def _check_recording_phases(self):
    mr = self._recording
    if mr.phase == PHASE_1 and mr.elapsed() >= mr.duration / 2:
        mr.phase = PHASE_2
    elif mr.phase == PHASE_2 and mr.elapsed() >= mr.duration:
        mr.phase = DONE
    elif mr.phase == DONE and mr.elapsed() >= mr.duration + 5:
        mr.phase = IDLE  # auto-reset after workers have saved
```

### Worker heartbeat polling

Workers check the flag in their existing 1s heartbeat loop. On phase change they call a registered callback (provided by observer or another profiling consumer). The server doesn't know about tracemalloc — it just manages the coordination.

### Triggers

**SIGUSR1 (CLI)**: Arbiter handles SIGUSR1 to toggle recording. Requires a PID file at startup.

**HTTP endpoint**: A worker receives a POST, sets the shared flag, all workers see it. Natural for toolbar.

### PID file

The arbiter should write a PID file at startup (e.g., derived from bind address). Useful for `plain memory record` CLI and other operational tooling.

## Empirical findings

Tested on Python 3.14 / macOS ARM:

| Operation                          | Time   | Notes                                      |
| ---------------------------------- | ------ | ------------------------------------------ |
| `tracemalloc.start(10)` at runtime | <0.1ms | Only tracks post-start allocations         |
| `take_snapshot()`                  | 7-15ms | On 529MB process, 7M allocated blocks      |
| `tracemalloc.stop()`               | 5ms    |                                            |
| Self-reported overhead             | ~0MB   | Because pre-existing allocations invisible |

tracemalloc reports ~20% of actual RSS growth (allocator overhead, PyObject headers, fragmentation). Correctly identifies leaking source lines regardless.

Multi-worker coordination via shared `multiprocessing.Value` with `get_context("spawn")` validated with 3 workers.
