---
depends_on:
  - metrics-log-exporter
---

# Metrics: http.server.request.duration

Add an `http.server.request.duration` histogram to the core request handler. Second metric — validates that each package instruments itself independently.

## Instrumentation

In `plain/internal/handlers/base.py`, create a histogram on the module-level meter:

```python
from opentelemetry import metrics

meter = metrics.get_meter("plain")
request_duration = meter.create_histogram("http.server.request.duration", unit="ms")
```

Record in `handle()` after the response is produced, alongside `_finalize_span()`:

```python
request_duration.record(duration_ms, {
    "http.request.method": request.method,
    "http.route": route,
    "http.response.status_code": response.status_code,
})
```

## Attribute cardinality

- `http.request.method` — GET, POST, etc. (low cardinality)
- `http.route` — URL pattern like `/<path:path>` (bounded by URL config, safe)
- `http.response.status_code` — numeric status (bounded, safe)
- Do NOT include full URL path — unbounded cardinality
