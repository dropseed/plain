---
name: plain-optimize
description: Captures and analyzes performance traces to identify slow queries and N+1 problems. Use when a page is slow, there are too many queries, or the user asks about performance.
context: fork
---

# Performance Optimization Workflow

## 1. Capture and Analyze

Make a request with tracing enabled — returns structured JSON with query counts, duplicates, issues, and span tree:

```
uv run plain observer request /path
uv run plain observer request /path --user 1
uv run plain observer request /path --method POST --data '{"key": "value"}'
```

The `--user` flag accepts a user ID or email.

The JSON output includes:

- `response.status` — HTTP status code
- `trace.query_count` / `trace.duplicate_query_count` — query summary
- `issues` — pre-detected problems (duplicate queries, exceptions)
- `queries` — each unique query with count, total duration, and source locations
- `spans` — nested span tree showing the request flow

## 2. Identify Bottlenecks

Check the `issues` array first — duplicate queries are flagged automatically with source locations. Then review:

- N+1 queries (duplicate queries with count > 1)
- Slow database queries (high `total_duration_ms`)
- Missing indexes
- Unnecessary work in hot paths

## 3. Apply Fixes

- Add `select_related()` / `prefetch_related()` for N+1
- Add database indexes for slow queries
- Cache expensive computations

## 4. Verify Improvement

Re-run `uv run plain observer request /path` and compare `query_count`, `duplicate_query_count`, and `trace.duration_ms`.
