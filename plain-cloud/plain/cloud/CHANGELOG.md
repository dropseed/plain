# plain-cloud changelog

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
