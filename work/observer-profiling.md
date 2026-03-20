---
labels:
  - plain-observer
  - plain-toolbar
depends_on:
  - server-memory-diagnostics
related:
  - metrics
---

# Observer profiling

Observer currently does **tracing** — spans, query timing, request lifecycle via OpenTelemetry. Profiling is a second axis: tracing tells you _what happened_, profiling tells you _why it was expensive_ (or _what's leaking_).

Three profiling dimensions, all sharing observer's toggle-on/toggle-off UX:

| Dimension     | Underlying tool            | Overhead | Model                                               |
| ------------- | -------------------------- | -------- | --------------------------------------------------- |
| Memory        | `tracemalloc`              | 5-30%    | Window-based (server recording plumbing)            |
| Line coverage | `sys.monitoring` (PEP 669) | ~5%      | Per-request (observer's existing per-request model) |
| CPU           | `cProfile` / `yappi`       | 10-30%   | Window-based (server recording plumbing)            |

None of these use OpenTelemetry — they're Python-specific profiling tools. Observer provides the toggle, storage, and display infrastructure.

## Memory profiling

Uses the server recording plumbing (see `server-memory-diagnostics`). Observer provides:

- **Three-snapshot analysis**: Snapshots A, B, C separated by traffic. Intersection of (B-A) and (C-B) filters one-time initialization, showing only sustained leaks. Validated empirically — filtered 86/89 false positives, correctly identified 3 leak lines.
- **DB storage**: Recording results stored alongside traces — which workers recorded, duration, request count, top allocations (file:line, size delta, count delta), RSS delta.
- **Toolbar UI**: "Record memory" button starts/stops recording. Results page shows grouped allocations by file/package with source lines.
- **Discrepancy reporting**: Compare tracemalloc-tracked growth vs. RSS growth. If RSS grew but tracemalloc found nothing → likely a C extension leak, suggest memray.

### Prior art

**derailed_benchmarks (Rails)**: Three-snapshot heap diff — the technique we adopted. **rack-mini-profiler**: Production-safe profiler with auth-gated memory panel. **Phoenix LiveDashboard**: Always-on process memory in a web UI — the gold standard for ambient awareness.

No framework provides built-in tracemalloc integration with runtime toggle and three-snapshot analysis.

### Memory pressure risk

Starting tracemalloc on a process near its memory limit adds ~20-50MB overhead. The UI should show current RSS and warn before starting. Auto-stop after a maximum duration (5 minutes) prevents accidentally leaving it running.

## Line coverage

Uses `sys.monitoring` (PEP 669, Python 3.12+). At ~5% overhead with the `DISABLE` return pattern, this is viable for per-request use — same model as existing observer tracing.

### How it works

```python
import sys

tool_id = sys.monitoring.COVERAGE_ID
sys.monitoring.use_tool_id(tool_id, "observer_coverage")
sys.monitoring.set_events(tool_id, sys.monitoring.events.LINE)

lines_hit = set()

def line_handler(code, line_number):
    lines_hit.add((code.co_filename, line_number))
    return sys.monitoring.DISABLE  # don't fire again for this location

sys.monitoring.register_callback(tool_id, sys.monitoring.events.LINE, line_handler)
```

### Per-request integration

Observer already toggles per-request via cookie/header. For line coverage:

1. Enable `sys.monitoring` LINE callbacks at request start (when observer is active)
2. Collect `(filename, line_number)` pairs, filtered to project code (skip stdlib, site-packages)
3. Call `restart_events()` after each observed request to reset for the next one
4. Store as part of the trace

The data: a set of `(file, line)` tuples showing exactly which lines executed during that request. Combined with query spans, you'd see both "what SQL ran" and "what code paths were taken."

### Considerations

- `sys.monitoring` events are per-interpreter, not per-thread — need bookkeeping to isolate to the observed request's thread
- Python 3.14 adds `BRANCH_LEFT`/`BRANCH_RIGHT` for branch coverage
- Tool IDs are limited (0-5) — `sys.monitoring.COVERAGE_ID` is the conventional choice
- File filtering is critical — without it you'd record stdlib/framework internals
- `restart_events()` cost is acceptable since it only runs for observed requests

### Use cases

- "Which code paths did this request take?" — helps understand complex view logic
- "Is this code path even reachable?" — dead code detection in production
- Comparing coverage between two requests — "why did request A hit this error path but B didn't?"

## CPU profiling

Window-based, uses the same server recording plumbing as memory profiling. Less researched — defer until memory and line coverage are shipped.

Likely approach: `cProfile` or `yappi` (yappi handles threads, which matters for the thread-pool worker model). Three-snapshot approach may apply here too (filter one-time import costs from sustained CPU hotspots).

## Toolbar integration

### Always-on (zero overhead)

Process RSS and allocated blocks in the toolbar footer. Uses `resource.getrusage` and `sys.getallocatedblocks()` — essentially free.

### Profiling controls

When observer is active, toolbar shows profiling buttons:

- **Record memory** — starts/stops a memory recording window
- **Line coverage** — toggles per-request line coverage (since it's per-request, it follows the existing observer mode toggle)

Results are viewable in the same admin interface as observer traces.

## Implementation order

1. **Toolbar RSS display** — always-on awareness, tiny change, immediate value
2. **Memory recording** — three-snapshot analysis, DB model for results, toolbar record button. Depends on server recording plumbing from `server-memory-diagnostics`.
3. **Line coverage** — `sys.monitoring` integration, per-request, stored alongside traces. Independent of server plumbing.
4. **CPU profiling** — similar to memory, uses same server plumbing. Lowest priority.

## Open questions

- **DB model**: Reuse observer's trace model (add a "recording" type) or new models? Memory recordings aren't per-request like traces — they're per-window, per-worker.
- **Toolbar UI**: What does "Record memory" look like? A button that shows a spinner for 60 seconds? A status bar? Needs design.
- **Line coverage granularity**: Store individual lines hit, or aggregate to "percentage of file covered"? Individual lines are more useful but more data.
- **Cross-request line coverage**: Could aggregate line coverage across many requests to build a "production coverage map" — which code is actually used in production vs. dead code. Interesting but scope creep.
