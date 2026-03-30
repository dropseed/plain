---
related:
  - metrics
  - otel-spans-proposal
---

# Metrics log exporter

Custom OTel `MetricExporter` in plain-observer that writes aggregated histogram data as structured log lines via `logging.getLogger("plain.metrics")`.

## MeterProvider setup

In `plain-observer`'s `Config.ready()`, configure a `MeterProvider` with a `PeriodicExportingMetricReader` that flushes to the custom exporter. Follows the same pattern as the existing `TracerProvider` setup — reuse the same `Resource`. On by default when observer is installed.

```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

reader = PeriodicExportingMetricReader(
    LoggingMetricExporter(),
    export_interval_millis=60_000,
)
provider = MeterProvider(metric_readers=[reader], resource=resource)
metrics.set_meter_provider(provider)
```

## Log line format

Logger name `plain.metrics`, message `"Metric flush"`. Both JSON and KeyValue formatters already emit all context fields, so the structured data flows naturally.

Fields per line:

- `metric` — name (e.g. `db.client.query.duration`)
- `unit` — measurement unit (e.g. `ms`)
- `count`, `sum`, `min`, `max` — aggregates (trivially re-aggregatable across processes)
- `p50`, `p95`, `p99` — pre-computed percentiles (convenience, not authoritative)
- `buckets` — boundary:count pairs for accurate re-aggregation in ClickHouse
- Any metric attributes (e.g. `db.operation.name`, `http.route`)

## Multi-process behavior

Each worker process has its own MeterProvider. Threads within a process share one (thread-safe). Each process emits independently. The collection side aggregates.

## Shutdown

`PeriodicExportingMetricReader` runs a background daemon thread. Call `provider.shutdown()` on process exit for a final flush. Hook into the server's shutdown path and register `atexit` for management commands.

## Settings

- `OBSERVER_METRICS_ENABLED` — default `True`, kill switch
- `OBSERVER_METRICS_FLUSH_INTERVAL` — default `60` seconds
