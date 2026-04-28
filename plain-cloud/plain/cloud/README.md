# plain.cloud

**Production observability via OTLP export to Plain Cloud.**

- [Overview](#overview)
- [Settings](#settings)
- [Sampling](#sampling)
- [What gets exported](#what-gets-exported)
- [Observer coexistence](#observer-coexistence)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use plain.cloud to export traces, metrics, and logs from your Plain app to Plain Cloud. The framework already instruments itself with OpenTelemetry spans and histograms — plain.cloud activates them by providing the OTLP exporters and bridges Python's `logging` module into OTLP log records.

Set one environment variable and your app starts pushing telemetry:

```
PLAIN_CLOUD_EXPORT_TOKEN=your-token
```

If `CLOUD_EXPORT_TOKEN` is not set, the package is a no-op — safe to install without configuration.

## Settings

| Setting                   | Default                               | Description                                                 |
| ------------------------- | ------------------------------------- | ----------------------------------------------------------- |
| `CLOUD_EXPORT_URL`        | `"https://ingest.plainframework.com"` | OTLP ingest endpoint (override to use a custom endpoint)    |
| `CLOUD_EXPORT_TOKEN`      | `""`                                  | Auth token for the export endpoint                          |
| `CLOUD_TRACE_SAMPLE_RATE` | `1.0`                                 | Probability of exporting a trace (0.0–1.0)                  |
| `CLOUD_EXPORT_LOGS`       | `True`                                | Set to `False` to disable OTLP log export                   |
| `CLOUD_LOG_LEVEL`         | `"INFO"`                              | Minimum severity exported via OTLP logs (level name or int) |

All settings can be set via `PLAIN_`-prefixed environment variables or in `app/settings.py`.

## Sampling

By default, all traces are exported. To reduce volume, set a sample rate:

```python
CLOUD_TRACE_SAMPLE_RATE = 0.1  # Export 10% of traces
```

Metrics are not affected by sampling — histograms aggregate in-process and export periodically regardless of the trace sample rate.

## What gets exported

**Traces** — HTTP request spans and database query spans instrumented by the framework.

**Metrics** — OTel histograms like `db.client.query.duration`, aggregated and pushed every 60 seconds.

**Logs** — Records from the `plain` and `app` loggers, plus anything propagating to the root logger, are bridged into OTLP log records and exported with `trace_id` / `span_id` set from the active span. The minimum severity is controlled by `CLOUD_LOG_LEVEL` (default `INFO`); the root logger's level is widened to that floor when needed so libraries using `getLogger(__name__)` reach the exporter. To prevent feedback loops, two sources are skipped on the export path: the `opentelemetry` namespace, and any record emitted from inside the OTLP exporter's background thread (e.g. urllib3 connection errors raised by the exporter's own HTTP call). Your application's urllib3 logs are exported normally.

## Observer coexistence

If [plain.observer](../../plain-observer/plain/observer/README.md) is also installed, both work simultaneously. plain.cloud handles production export while observer provides the local dev toolbar and admin trace viewer. Observer detects the existing TracerProvider and layers its sampler and span processor on top.

## FAQs

#### Do I need plain.observer to use plain.cloud?

No. plain.cloud works independently. Observer is for local dev tooling; plain.cloud is for production export.

#### What happens if the export endpoint is unreachable?

The OTLP exporters batch and retry automatically. If the endpoint is down, telemetry is dropped after retries — it does not block your application.

#### Does this add latency to requests?

No. Trace spans are exported in a background thread via `BatchSpanProcessor`. Metrics are flushed periodically by a background thread. Neither blocks request handling.

## Installation

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.cloud",
    # ...
]
```

Place `plain.cloud` **before** `plain.observer` in `INSTALLED_PACKAGES` so it sets up the TracerProvider first.
