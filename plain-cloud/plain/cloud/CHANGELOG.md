# plain-cloud changelog

## [0.1.1](https://github.com/dropseed/plain/releases/plain-cloud@0.1.1) (2026-04-01)

### What's changed

- Updated export endpoint URLs in docs and default settings from `plaincloud.com` to `plainframework.com/otel`. ([15bb896cdbe6](https://github.com/dropseed/plain/commit/15bb896cdbe6))

### Upgrade instructions

- If you have `PLAIN_CLOUD_EXPORT_URL` set to `https://ingest.plaincloud.com`, update it to `https://plainframework.com/otel`.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-cloud@0.1.0) (2026-04-01)

### What's changed

- **Initial release.** Sets up OpenTelemetry TracerProvider and MeterProvider with OTLP HTTP exporters, pushing traces and metrics to Plain Cloud. Configure with `CLOUD_EXPORT_URL` and `CLOUD_EXPORT_TOKEN` settings. Includes head-based trace sampling via `CLOUD_TRACE_SAMPLE_RATE`. Inactive when `CLOUD_EXPORT_URL` is not set. Coexists with plain-observer — observer layers its sampler and span processor on top. ([e3971506cb](https://github.com/dropseed/plain/commit/e3971506cb))
