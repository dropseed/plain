---
related:
  - observer-testing
  - postgres-cli-and-insights
  - models-non-blocking-ddl
---

# Plain Models Index Suggestions

## Overview

Automatically suggest database indexes based on actual query patterns observed in production. This combines query telemetry with heuristics (and potentially LLM assistance) to surface actionable index recommendations.

## Key Insights from PlanetScale's Approach

Reference: https://planetscale.com/blog/postgres-new-index-suggestions

### 1. Filter First, Suggest Second

The critical insight is treating index recommendation as an **information retrieval problem first**. Instead of asking "what indexes could help?", narrow the search space using actual workload data before generating suggestions.

This inverts typical AI workflows - use telemetry to identify candidates, then validate suggestions, rather than generating suggestions and hoping they're relevant.

### 2. Query Selection Heuristics

Not every slow query deserves an index. Filter candidates using:

- **High rows read vs rows returned ratio** - Indicates table scans that could benefit from indexes
- **Significant query runtime share** - Only queries responsible for ≥0.1% of aggregated runtime
- **Minimum execution frequency** - Avoid ad-hoc queries; indexes have storage/memory overhead
- **Table relevance** - Only consider tables actually referenced by candidate queries

### 3. Schema Reduction for LLM Prompts

When using LLMs for suggestion generation, filter the schema down to only tables referenced by candidate queries. This keeps prompts smaller, more focused, and reduces hallucination risk.

Each suggested index should explicitly reference which query it targets - this creates accountability and makes validation straightforward.

### 4. Two-Phase Validation

1. **Syntactic validation** - Ensure generated `CREATE INDEX` statements are valid SQL
2. **Performance validation** - Use hypothetical indexes (HypoPG extension) to measure actual improvement via `EXPLAIN` cost comparison

### 5. Address Two LLM Failure Modes

LLMs have two key failure modes for this task:

- **Over-recommendation** - LLMs want to help, so they suggest indexes even when nothing needs to change. Fix this by using query performance data to verify necessity _before_ asking for suggestions.
- **Inaccuracy** - Generated SQL may be invalid or ineffective. Fix this with robust validation preventing deployment of bad suggestions.

### 6. Avoid These Pitfalls

- Suggesting indexes for infrequently-run queries (overhead not worth it)
- Surfacing suggestions without measurable performance gains
- Trusting unvalidated LLM outputs in production

## Potential Implementation for Plain

### Data Collection

`plain-observe` already captures request data. We could extend this to capture:

- Query patterns (parameterized queries)
- Execution counts
- Rows examined vs rows returned (from `EXPLAIN ANALYZE`)
- Total time spent per query pattern

### Analysis Approach

1. Aggregate query patterns over a time window
2. Apply heuristics to identify candidate queries
3. Generate potential index suggestions (rule-based or LLM-assisted)
4. Validate using `EXPLAIN` with hypothetical indexes
5. Surface only suggestions with significant estimated improvement

### Output

Could be:

- A management command: `plain models suggest-indexes`
- A toolbar panel showing index recommendations
- Part of preflight checks for performance warnings

### SARGable Query Detection

Functions wrapping indexed columns kill index usage. The observer could detect patterns like `WHERE date_trunc('day', created_at) = '2023-01-01'` and suggest either a range rewrite or a functional index. This is one of the most common "why isn't my index being used?" issues.

### Invalid Index Detection

Failed `CREATE INDEX CONCURRENTLY` leaves INVALID indexes — maintained on writes, never used for reads. These are pure overhead and should be flagged for cleanup. See `models-non-blocking-ddl` for the full failure mode.

```sql
SELECT indexrelname FROM pg_stat_user_indexes s
JOIN pg_index i ON s.indexrelid = i.indexrelid WHERE NOT i.indisvalid;
```

### HOT Update Analysis

Tables with low HOT (Heap-Only Tuple) update ratios may have unnecessary indexes on frequently-updated columns. If `n_tup_hot_upd / n_tup_upd < 0.9` on a write-heavy table, suggest:

1. Removing indexes on columns like `status` and `updated_at` unless they're query-critical
2. Lowering `fillfactor` to 70-80% to leave room for in-place updates

### Write Amplification Awareness

Each additional index adds write-path overhead. Benchmarks show moving from 7 to 39 indexes causes a ~58% throughput drop ([Percona PG 17.4 benchmark](https://www.percona.com/blog/benchmarking-postgresql-the-hidden-cost-of-over-indexing/)). Per-table guidelines: <5 normal, 5-10 review, >10 audit.

## Open Questions

- How to handle multi-column index suggestions?
- Should we suggest removing unused indexes too? (Yes — with the PlanetScale-style filter: exclude unique, expression, and constraint-backing indexes)
- Integration with migrations - auto-generate migration files?
- How to capture query telemetry without significant overhead?
- Should we use HypoPG for validating suggestions before recommending them?
