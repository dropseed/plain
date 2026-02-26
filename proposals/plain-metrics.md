# plain: Framework-level metrics via OpenTelemetry

- Plain already uses OTel for tracing in the core request handler — extend this to also record OTel metrics (counters, histograms)
- Instrument the request lifecycle automatically: request count, duration, status codes
- Users add domain-specific metrics using the standard OTel metrics API
- A separate exporter (in plain-observer or a new package) configures how metrics are exposed — Prometheus `/metrics` endpoint, OTLP push, etc.

## Background: how Prometheus-style metrics work

Prometheus uses a pull model. Your app exposes a `/metrics` HTTP endpoint that returns plain text with current counter/gauge/histogram values. Prometheus scrapes this endpoint on an interval (e.g. every 30s) and stores the time series data on its own disk. The app doesn't persist anything — metrics are just in-memory numbers that get incremented as things happen.

Metric types:

- **Counter** — only goes up (request count, errors). Prometheus calculates rates from the deltas between scrapes. Resets to 0 on app restart, which Prometheus handles automatically.
- **Gauge** — goes up and down (active connections, queue depth). Trickier with restarts since a reset to 0 looks like a real drop.
- **Histogram** — buckets of observations (request latency). Records counts of values falling into configurable ranges.

## Why OTel metrics (not raw prometheus_client)

Plain already depends on OTel for tracing. OTel's metrics API is the same SDK, just a different signal. Benefits:

- **One instrumentation standard** for both tracing and metrics
- **No vendor lock-in** — swap exporters without changing app code (Prometheus today, Datadog tomorrow)
- **Zero cost when unused** — OTel metrics no-op without a configured MeterProvider
- **Multi-process friendly** — OTLP push exporters let each worker push independently, avoiding the shared-tmpfs hack that raw `prometheus_client` needs with multiple gunicorn workers

## Core instrumentation (in `plain`)

Add OTel metrics alongside the existing tracing in `BaseHandler.get_response()`:

```python
from opentelemetry import metrics

meter = metrics.get_meter("plain")

request_counter = meter.create_counter(
    "http.server.request.count",
    description="Total HTTP requests",
)
request_duration = meter.create_histogram(
    "http.server.request.duration",
    unit="ms",
    description="Request duration",
)
```

Then in the handler, alongside the existing span creation:

```python
start = time.perf_counter()
response = self._middleware_chain(request)
duration = (time.perf_counter() - start) * 1000

attrs = {
    "http.request.method": request.method,
    "http.route": route,
    "http.response.status_code": response.status_code,
}
request_counter.add(1, attrs)
request_duration.record(duration, attrs)
```

This is nearly free — a few in-memory increments next to the tracing that already happens. Without a configured MeterProvider, these are no-ops.

## Exporter configuration (in plain-observer or new package)

The exporter turns in-memory metrics into something external systems can read. This could live in `plain-observer` (which already configures OTel tracing) or a separate `plain-metrics` package.

### Prometheus exporter

Uses `opentelemetry-exporter-prometheus` to serve a `/metrics` endpoint:

```python
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry import metrics

reader = PrometheusMetricReader()
provider = metrics.MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
```

Then a simple view that returns `generate_latest()` in Prometheus exposition format.

### OTLP push exporter

Pushes to an OTel Collector sidecar, which forwards to any backend:

```python
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

reader = PeriodicExportingMetricReader(OTLPMetricExporter())
provider = metrics.MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
```

## User-defined metrics

Users add their own domain metrics using the OTel API:

```python
from opentelemetry import metrics

meter = metrics.get_meter("myapp")
webhook_counter = meter.create_counter("webhooks.received")

# In a view or job
webhook_counter.add(1, {"event_type": "pull_request"})
```

These automatically flow through whatever exporter is configured.

## Open questions

- Should the core instrumentation be on by default, or opt-in via a setting?
- Does the exporter config belong in plain-observer (it already manages OTel setup) or a separate package?
- What labels/attributes should the default request metrics include? Need to be careful about cardinality — route patterns are fine, full paths are not.
- Should plain-jobs also auto-instrument (job count, duration, queue depth)?
