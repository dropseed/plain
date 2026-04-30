# plain-cloud changelog

## [0.3.2](https://github.com/dropseed/plain/releases/plain-cloud@0.3.2) (2026-04-30)

### What's changed

- **Suppressed Sentry capture for OTLP exporter batch failures.** The OpenTelemetry SDK's exporters log `"Failed to export X batch"` at ERROR after retries are exhausted, which Sentry's `LoggingIntegration` would otherwise turn into an issue per app per incident — noise the app owner can't act on (network/edge timeouts, ingest backend hiccups). The records still flow to console/file/etc.; only the Sentry capture is suppressed. Mirrors the Sentry SDK's own self-protection for `sentry_sdk.errors` and `urllib3.connectionpool`. ([eb771d82d2de](https://github.com/dropseed/plain/commit/eb771d82d2de))

### Upgrade instructions

- No changes required.

## [0.3.1](https://github.com/dropseed/plain/releases/plain-cloud@0.3.1) (2026-04-28)

### What's changed

- The OTLP span, metric, and log exporters now use gzip compression and a 30-second timeout, reducing egress bandwidth and giving slow ingest endpoints more headroom before requests are dropped. ([891864bcf710](https://github.com/dropseed/plain/commit/891864bcf710))

### Upgrade instructions

- No changes required.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-cloud@0.3.0) (2026-04-27)

### What's changed

- **Added OTLP log export.** Records from the `plain` and `app` loggers, plus anything propagating to the root logger, are bridged into OTLP log records and exported alongside traces and metrics, with `trace_id` / `span_id` populated from the active span. Two new settings: `CLOUD_EXPORT_LOGS` (default `True`) and `CLOUD_LOG_LEVEL` (default `"INFO"`, accepts a level name or int). The root logger's effective level is widened upward to `CLOUD_LOG_LEVEL` when narrower so libraries using `getLogger(__name__)` reach the exporter; it is never narrowed. To prevent feedback loops under transport failure, the exporter ignores records from the `opentelemetry` namespace and from any OTel SDK exporter thread (`OtelBatchSpanRecordProcessor`, `OtelBatchLogRecordProcessor`, `OtelPeriodicExportingMetricReader`). Application urllib3 logs are exported normally. ([3937adee2153](https://github.com/dropseed/plain/commit/3937adee2153))
- Added a `LoggerProvider` collision check that mirrors the existing `TracerProvider` check, so `plain.cloud` will fail loudly with the "list before plain.observer" message if another package has already installed a logger provider. ([3937adee2153](https://github.com/dropseed/plain/commit/3937adee2153))

### Upgrade instructions

- No changes required. To opt out of log export, set `CLOUD_EXPORT_LOGS=False` (or `PLAIN_CLOUD_EXPORT_LOGS=false`). To raise/lower the severity floor, set `CLOUD_LOG_LEVEL` (e.g. `"WARNING"`).

## [0.2.0](https://github.com/dropseed/plain/releases/plain-cloud@0.2.0) (2026-04-27)

### What's changed

- **Changed the default `CLOUD_EXPORT_URL` to `https://ingest.plainframework.com`** (was `https://plainframework.com/otel`). Projects relying on the default will now export to the dedicated ingest subdomain. ([e58c02eaab9e](https://github.com/dropseed/plain/commit/e58c02eaab9e))

### Upgrade instructions

- If you were depending on the previous default, set `PLAIN_CLOUD_EXPORT_URL=https://plainframework.com/otel` (or assign `CLOUD_EXPORT_URL` in `app/settings.py`) to keep the old endpoint. Otherwise no changes required.

## [0.1.5](https://github.com/dropseed/plain/releases/plain-cloud@0.1.5) (2026-04-13)

### What's changed

- Removed redundant `atexit` shutdown registrations that duplicated the shutdown hooks already registered elsewhere. ([dfb2ce53cd5c](https://github.com/dropseed/plain/commit/dfb2ce53cd5c))

### Upgrade instructions

- No changes required.

## [0.1.4](https://github.com/dropseed/plain/releases/plain-cloud@0.1.4) (2026-04-02)

### What's changed

- Switched metrics export to delta temporality for Counter, Histogram, and UpDownCounter. Each export now contains only the increment since the last collection, making server-side aggregation in ClickHouse straightforward. ([ab431cb5ffe6](https://github.com/dropseed/plain/commit/ab431cb5ffe6))

### Upgrade instructions

- No changes required.

## [0.1.3](https://github.com/dropseed/plain/releases/plain-cloud@0.1.3) (2026-04-01)

### What's changed

- Added `CLOUD_EXPORT_ENABLED` setting (defaults to `True`) to allow disabling all OTEL reporting without removing the token. Set `PLAIN_CLOUD_EXPORT_ENABLED=false` to turn it off. ([e9c4d140b227](https://github.com/dropseed/plain/commit/e9c4d140b227))
- Raises `RuntimeError` if another tracer provider is already configured when plain.cloud initializes — ensures `plain.cloud` is listed before `plain.observer` in `INSTALLED_PACKAGES`. ([40252d96ce7d](https://github.com/dropseed/plain/commit/40252d96ce7d))

### Upgrade instructions

- No changes required.

## [0.1.2](https://github.com/dropseed/plain/releases/plain-cloud@0.1.2) (2026-04-01)

### What's changed

- `CLOUD_EXPORT_URL` now defaults to `https://plainframework.com/otel` — no need to set it manually. Export is gated on `CLOUD_EXPORT_TOKEN` instead, so only one env var is needed to start pushing telemetry. ([fa711758acda](https://github.com/dropseed/plain/commit/fa711758acda))

### Upgrade instructions

- If you had `PLAIN_CLOUD_EXPORT_URL` set to `https://plainframework.com/otel`, you can remove it — that's now the default.
- If you relied on leaving `CLOUD_EXPORT_URL` empty to disable export, set `CLOUD_EXPORT_TOKEN` to empty instead (or just don't set it).

## [0.1.1](https://github.com/dropseed/plain/releases/plain-cloud@0.1.1) (2026-04-01)

### What's changed

- Updated export endpoint URLs in docs and default settings from `plaincloud.com` to `plainframework.com/otel`. ([15bb896cdbe6](https://github.com/dropseed/plain/commit/15bb896cdbe6))

### Upgrade instructions

- If you have `PLAIN_CLOUD_EXPORT_URL` set to `https://ingest.plaincloud.com`, update it to `https://plainframework.com/otel`.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-cloud@0.1.0) (2026-04-01)

### What's changed

- **Initial release.** Sets up OpenTelemetry TracerProvider and MeterProvider with OTLP HTTP exporters, pushing traces and metrics to Plain Cloud. Configure with `CLOUD_EXPORT_URL` and `CLOUD_EXPORT_TOKEN` settings. Includes head-based trace sampling via `CLOUD_TRACE_SAMPLE_RATE`. Inactive when `CLOUD_EXPORT_URL` is not set. Coexists with plain-observer — observer layers its sampler and span processor on top. ([e3971506cb](https://github.com/dropseed/plain/commit/e3971506cb))
