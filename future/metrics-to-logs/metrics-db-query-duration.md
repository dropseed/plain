---
depends_on:
  - metrics-log-exporter
---

# Metrics: db.client.query.duration

Add a `db.client.query.duration` histogram to plain-postgres. First real metric — proves the meter-to-logs pipeline end to end.

## Instrumentation

In `plain/postgres/otel.py`, create a histogram on the module-level meter and record the query duration at the end of `db_span()`:

```python
from opentelemetry import metrics

meter = metrics.get_meter("plain.postgres")
query_duration = meter.create_histogram("db.client.query.duration", unit="ms")
```

Record inside `db_span()` after the yield, with attributes for operation and collection:

```python
query_duration.record(duration_ms, {
    "db.operation.name": operation,
    "db.collection.name": collection_name,
})
```

Without a configured MeterProvider (i.e. observer not installed), this is a no-op — standard OTel behavior.

## Attribute cardinality

- `db.operation.name` — SELECT, INSERT, UPDATE, DELETE (low cardinality, safe)
- `db.collection.name` — table name (bounded by schema, safe)
- Do NOT include `db.query.text` — unbounded cardinality, would explode histogram memory

## Histogram buckets

Default OTel exponential histogram is fine to start. If explicit boundaries are needed later: `[0, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]` ms.
