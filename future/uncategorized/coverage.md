---
related:
  - observer-profiling
---

# Coverage

Plain's own code coverage built on `sys.monitoring` (PEP 669). Replaces coverage.py with something tighter — counts instead of booleans, integrated into the framework, and accessible to agents.

## Why not coverage.py

- Reports are boolean (covered/not covered) even though it collects counts internally
- Separate tool with its own config, own reports, own HTML output — doesn't talk to anything else
- Still uses `sys.settrace`, not `sys.monitoring`
- No concept of per-request coverage
- No way to compare test coverage against production usage

## Core primitive

A small `sys.monitoring` wrapper that collects `{file: {line: count}}` dicts. Context-manager interface for easy integration:

```python
with line_counter(include=["app/", "plain/"]) as counts:
    # run code
# counts = {"app/views.py": {14: 1, 15: 3, 22: 150}, ...}
```

Key details:

- Uses `sys.monitoring.COVERAGE_ID` with `LINE` events
- ~5% overhead with the `DISABLE` return pattern (re-enable via `restart_events()` between collection windows)
- File filtering is critical — skip stdlib, site-packages, only record project code
- Collects **counts**, not just boolean hit/miss — this is the differentiator
- `sys.monitoring` is per-interpreter, not per-thread — need thread-aware bookkeeping for the server context
- Python 3.14 adds `BRANCH_LEFT`/`BRANCH_RIGHT` for branch coverage (future enhancement)
- Tool IDs are limited (0-5) — `COVERAGE_ID` is the conventional choice

## Two consumers, same data

### Test coverage

```bash
uv run plain test --coverage
```

Wraps the full test run in the line counter. Accumulates counts across all tests. Stores results in the dev database (or a local file — TBD).

Counts matter here: "line 42 was hit 4,000 times across tests" vs "line 42 was hit once" tells you something about test depth. A line hit once might be covered by accident.

### Observer coverage (dev + production)

Per-request coverage, toggled the same way observer tracing is toggled (cookie/header). Stores `{file: {line: count}}` alongside the trace in the DB.

In dev: "which code paths did this request take?" — helps understand view logic, spot loops.
In production: aggregate across requests to build a coverage map of what code is actually used.

Both consumers produce the same `{file: {line: count}}` shape. Storage differs (test run = one big aggregate, observer = per-request attached to a trace) but the data is interchangeable.

## What you can do with both

The interesting queries come from having both test and production/request coverage in the same system:

- **Untested production code**: lines hot in production, uncovered by tests → risk
- **Wasted tests**: lines heavily tested but never hit in production → testing dead code
- **Shallow tests**: line hit 500 times per request but only 2 times across all tests → tests aren't exercising the realistic case
- **Dead code**: cold in both tests and production → safe to delete
- **Loop detection**: a line hit 150 times in a single request → same N+1 signal observer catches with queries, but now visible at the code level

## Agent access

This might be the most important interface. Agents working on the codebase get coverage as ambient context:

```bash
# After running tests with coverage
uv run plain coverage show app/views.py
# → line-by-line counts from last test run

# Integrated into observer's existing CLI
uv run plain observer request /path --coverage
# → trace JSON now includes line counts alongside query analysis

# Cross-reference
uv run plain coverage compare app/views.py
# → shows test counts vs production/request counts side by side
```

An agent investigating a bug runs `observer request` with coverage, sees exactly which branch was taken. An agent writing tests runs `plain test --coverage`, sees uncovered lines, writes tests targeting them, runs again. An agent doing cleanup checks both — if a function is cold everywhere, it deletes it confidently.

## Display

Secondary to CLI/agent access, but valuable:

- **Observer admin**: trace detail page gets a "code" tab showing line counts for that request, with source
- **Toolbar**: quick overlay showing coverage for the current file/view during dev
- **Test report**: terminal summary after `plain test --coverage` — files, percentages, uncovered line ranges

All views show counts, not just red/green. A heatmap style (darker = more hits) makes hot paths immediately visible.

## Open questions

- **Package home**: Standalone `plain-coverage`? Part of `plain-code`? A core module that observer and pytest hook into?
- **Storage for test coverage**: Dev database (consistent with observer) or local file (works without a running app)? DB is nicer for unified queries but means test coverage requires DB setup.
- **Aggregation in production**: How to aggregate per-request coverage into a "production coverage map" without unbounded storage growth? Rolling window? Periodic snapshots? Only store aggregates, not per-request line data?
- **Thread isolation**: `sys.monitoring` is per-interpreter. In the threaded server, need to attribute line events to the correct request. Options: check `threading.current_thread()` in the callback (adds overhead), or only enable coverage for one request at a time.
- **Interaction with observer profiling**: The observer-profiling exploration has line coverage as one of three profiling dimensions. This exploration expands it into a standalone feature that also covers tests. The observer integration described here supersedes the line coverage section in observer-profiling.
