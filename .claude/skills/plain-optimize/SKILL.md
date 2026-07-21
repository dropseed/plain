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

`traces` is normally a list — **one entry per request**, so a followed redirect chain returns one per hop in hop order. Analyze each on its own; the last entry is the page that actually rendered. Never sum counts across hops: a query the framework runs once per request would look like a repeat that no change can fix.

**Check `trace_note` before indexing.** `traces` is `null` when the OpenTelemetry SDK isn't installed and `[]` when nothing was captured; in both cases a `trace_note` sibling key says why. Report that instead of indexing into nothing.

**A failed request returns a different shape.** If the view raised, the command exits 1 and emits `{"error": "...", "traces": [...]}` — no `response` key. The trace is still there, and `analysis.exceptions` carries the stacktrace, so this is the payload to read when debugging a 500. Branch on `"response" in payload` before reaching for it.

Each entry has `name` (e.g. `GET /admin/p/user`, including any query string) and `request_id` — which matches `response.request_id` for the hop that rendered — plus `analysis` (derived) and `spans` (raw):

- `analysis.query_count` — statements executed in this request
- `analysis.transaction_count` — transaction-control statements, counted apart from queries. With `plain.postgres` this is savepoint bookkeeping; `BEGIN`/`COMMIT` are issued outside the instrumented cursor and never appear
- `analysis.duration_ms` — that request's duration
- `analysis.exceptions` — exceptions recorded on any span, with `span`, `error_type`, `message`, `stacktrace`
- `analysis.queries` — each distinct statement with `count`, `total_duration_ms`, and `sources`, **slowest first**
- `sources` — the call sites that issued the statement, as `path:line in function` strings. The path says whose code it is: project paths vs installed-package (`site-packages`) paths
- `spans` — raw OpenTelemetry spans, a flat list (`parent_span_id` gives the structure)

`count` means one thing: how many times that statement ran in that request. Nothing is pre-diagnosed.

## 2. Identify Bottlenecks

**You do the diagnosing.** The trace reports what ran; deciding what is wrong with it is the job. Read `analysis.queries` and look for:

- **Repeats** — `count > 1` is the N+1 shape. Go read the code at the recorded call sites before concluding: three executions from three branches is not the same as three from a loop, and only the source tells you which. A source is where the query _executed_, which for lazy querysets can be framework code (a paginator, a template render) even though project code built the queryset — a repeat with only `site-packages` sources still usually traces back to a queryset the project constructed.
- **Slow statements** — high `total_duration_ms`. A single slow query outranks a dozen fast repeats.
- **Cost the counts don't show** — `duration_ms` far exceeding the sum of query time means the time went somewhere else; read `spans` for it.
- Missing indexes, unnecessary work in hot paths.

Never sum counts across hops — a query the framework runs once per request would look like a repeat that no change can fix.

## 3. Apply Fixes

- Add `select_related()` / `prefetch_related()` for N+1
- Add database indexes for slow queries
- Cache expensive computations

## 4. Verify Improvement

Re-run `uv run plain request /path --json` and compare `analysis.query_count`, the `count` on the statement you changed, and `analysis.duration_ms` for the same trace — match traces by `name`, not position, since a fix can change the redirect chain.
