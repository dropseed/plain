---
name: plain-optimize
description: Captures and analyzes performance traces to identify slow queries and N+1 problems. Use when a page is slow, there are too many queries, or the user asks about performance.
context: fork
---

# Performance Optimization Workflow

## 1. Capture and Analyze

Make a request and get structured JSON — response metadata plus a full trace analysis:

```
uv run plain request /path --json
uv run plain request /path --json --user 1
uv run plain request /path --json --method POST --data '{"key": "value"}'
```

The `--user` flag accepts a user ID or email.

The `trace` object has two parts — `analysis` (derived) and `spans` (raw):

- `analysis.query_count` / `analysis.duplicate_query_count` — query summary
- `analysis.duration_ms` — total trace duration
- `analysis.issues` — pre-detected problems (N+1 queries, exceptions)
- `analysis.queries` — each unique query with count, total duration, and source locations
- `spans` — raw OpenTelemetry spans, a flat list (`parent_span_id` gives the structure)

## 2. Identify Bottlenecks

Check `analysis.issues` first — duplicate queries are flagged automatically with source locations. Then review:

- N+1 queries (duplicate queries with count > 1)
- Slow database queries (high `total_duration_ms`)
- Missing indexes
- Unnecessary work in hot paths

## 3. Apply Fixes

- Add `select_related()` / `prefetch_related()` for N+1
- Add database indexes for slow queries
- Cache expensive computations

## 4. Verify Improvement

Re-run `uv run plain request /path --json` and compare `analysis.query_count`, `analysis.duplicate_query_count`, and `analysis.duration_ms`.
