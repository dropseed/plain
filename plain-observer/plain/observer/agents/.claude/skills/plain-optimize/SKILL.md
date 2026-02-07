---
name: plain-optimize
description: Captures and analyzes performance traces to identify slow queries and N+1 problems. Use when analyzing performance or optimizing database queries.
---

# Performance Optimization Workflow

## 1. Capture Traces

Make a request with tracing enabled:

```
uv run plain request /path --user 1 --header "Observer: persist"
```

## 2. Find Traces

```
uv run plain observer traces --request-id <request-id>
```

## 3. Analyze Trace

```
uv run plain observer trace <trace-id> --json
```

## 4. Identify Bottlenecks

Look for:

- N+1 queries (many similar queries)
- Slow database queries
- Missing indexes
- Unnecessary work in hot paths

## 5. Apply Fixes

- Add `select_related()` / `prefetch_related()` for N+1
- Add database indexes for slow queries
- Cache expensive computations

## 6. Verify Improvement

Re-run the trace and compare.
