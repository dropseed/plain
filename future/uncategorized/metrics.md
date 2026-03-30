---
related:
  - metrics-log-exporter
  - otel-spans-proposal
  - admin-live-charts
  - auth-otel-user-context
---

# Metrics: Prometheus and OTLP exporters

Alternative metric export targets beyond the log-based approach in the `metrics-to-logs` arc. Once framework packages instrument themselves with OTel histograms, additional exporters can be swapped in without changing instrumentation code.

## Prometheus exporter

Uses `opentelemetry-exporter-prometheus` to serve a `/metrics` endpoint:

```python
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry import metrics

reader = PrometheusMetricReader()
provider = metrics.MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
```

Then a simple view that returns `generate_latest()` in Prometheus exposition format.

Multi-process caveat: Prometheus pull model requires shared state across workers. The `prometheus_client` library uses a shared tmpfs directory for this. OTel's Prometheus exporter may handle this differently — needs investigation.

## OTLP push exporter

Pushes to an OTel Collector sidecar, which forwards to any backend:

```python
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

reader = PeriodicExportingMetricReader(OTLPMetricExporter())
provider = metrics.MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
```

Multi-process friendly — each worker pushes independently.

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
