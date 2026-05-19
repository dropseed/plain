# plain-connect changelog

## [0.5.0](https://github.com/dropseed/plain/releases/plain-connect@0.5.0) (2026-05-19)

### What's changed

- Pageview beacons now carry the matched URL route pattern (e.g. `/blog/<slug>/`) on the server-rendered initial load, mirroring the `http.route` span attribute. This lets pageviews aggregate by view instead of by raw URL. SPA navigations send a blank route. ([93f12bc8c6](https://github.com/dropseed/plain/commit/93f12bc8c6))
- Docs now note that a strict `Content-Security-Policy` must allow the pageview ingest host in `connect-src` — beacons are sent with `navigator.sendBeacon`, and the browser blocks them otherwise. ([2cab277d3e](https://github.com/dropseed/plain/commit/2cab277d3e))

### Upgrade instructions

- No changes required.

## [0.4.0](https://github.com/dropseed/plain/releases/plain-connect@0.4.0) (2026-05-18)

### What's changed

- New `{% connect_pageviews %}` template tag for first-party pageview tracking, independent of the OTLP export. Drop it into your base template before `</body>` and set `CONNECT_PAGEVIEWS_TOKEN` to enable it — it reports the URL, title, referrer, and an anonymous id on each page load and SPA navigation (`pushState` / back-forward). The tag renders nothing until the token is set. ([ab468e6bf9](https://github.com/dropseed/plain/commit/ab468e6bf9))
- Optional signed-in user attribution: set `CONNECT_PAGEVIEWS_IDENTITY_KEY` and the tag encrypts the authenticated user's id (AES-256-GCM) into an opaque token, so the raw id never appears in page HTML. The user is read from `plain.auth` when installed; apps without it still get anonymous pageviews. ([ab468e6bf9](https://github.com/dropseed/plain/commit/ab468e6bf9))
- New `CONNECT_PAGEVIEWS_TOKEN`, `CONNECT_PAGEVIEWS_IDENTITY_KEY`, and `CONNECT_PAGEVIEWS_URL` settings. ([ab468e6bf9](https://github.com/dropseed/plain/commit/ab468e6bf9))

### Upgrade instructions

- No changes required. Pageview tracking is opt-in — it stays off until you add the `{% connect_pageviews %}` tag and set `CONNECT_PAGEVIEWS_TOKEN`.

## [0.3.5](https://github.com/dropseed/plain/releases/plain-connect@0.3.5) (2026-05-08)

### What's changed

- New agent rule (`plain-connect.md`) that points AI agents at the separate `plain-cloud` CLI for reading telemetry data back (production exceptions, slow endpoints, slow queries, recent deploys). Discovery-first guidance: use `plain-cloud openapi | jq '.paths | keys'` instead of hardcoding paths. ([c3d58e7a17](https://github.com/dropseed/plain/commit/c3d58e7a17))

### Upgrade instructions

- Run `plain agents install` to pick up the new rule.

## [0.3.4](https://github.com/dropseed/plain/releases/plain-connect@0.3.4) (2026-05-07)

### What's changed

- **Renamed `plain-cloud` to `plain-connect`.** The package, module path, and config label all change: `plain.cloud` → `plain.connect`, and the package label `plaincloud` → `plainconnect`. All settings move from the `CLOUD_*` prefix to `CONNECT_*` (e.g. `CLOUD_EXPORT_TOKEN` → `CONNECT_EXPORT_TOKEN`, `PLAIN_CLOUD_EXPORT_TOKEN` → `PLAIN_CONNECT_EXPORT_TOKEN`). The destination service is still Plain Cloud — `plain-connect` is the app integration package that ships telemetry to it. ([304fc185cc](https://github.com/dropseed/plain/commit/304fc185cc))

### Upgrade instructions

- Replace `plain-cloud` with `plain-connect` in your dependencies (e.g. `pyproject.toml`).
- In `app/settings.py`, replace `"plain.cloud"` with `"plain.connect"` in `INSTALLED_PACKAGES`.
- Rename any `CLOUD_*` settings to `CONNECT_*`, and any `PLAIN_CLOUD_*` env vars to `PLAIN_CONNECT_*`.

## [0.3.3](https://github.com/dropseed/plain/releases/plain-connect@0.3.3) (2026-05-05)

### What's changed

- Exposes `__version__` from `importlib.metadata` on `plain.cloud` for version probes that don't want to scrape pip metadata. ([c6cf6edb](https://github.com/dropseed/plain/commit/c6cf6edb))

### Upgrade instructions

- No changes required.

## [0.3.2](https://github.com/dropseed/plain/releases/plain-connect@0.3.2) (2026-04-30)

### What's changed

- **Suppressed Sentry capture for OTLP exporter batch failures.** The OpenTelemetry SDK's exporters log `"Failed to export X batch"` at ERROR after retries are exhausted, which Sentry's `LoggingIntegration` would otherwise turn into an issue per app per incident — noise the app owner can't act on (network/edge timeouts, ingest backend hiccups). The records still flow to console/file/etc.; only the Sentry capture is suppressed. Mirrors the Sentry SDK's own self-protection for `sentry_sdk.errors` and `urllib3.connectionpool`. ([eb771d82d2de](https://github.com/dropseed/plain/commit/eb771d82d2de))

### Upgrade instructions

- No changes required.

## [0.3.1](https://github.com/dropseed/plain/releases/plain-connect@0.3.1) (2026-04-28)

### What's changed

- The OTLP span, metric, and log exporters now use gzip compression and a 30-second timeout, reducing egress bandwidth and giving slow ingest endpoints more headroom before requests are dropped. ([891864bcf710](https://github.com/dropseed/plain/commit/891864bcf710))

### Upgrade instructions

- No changes required.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-connect@0.3.0) (2026-04-27)

### What's changed

- **Added OTLP log export.** Records from the `plain` and `app` loggers, plus anything propagating to the root logger, are bridged into OTLP log records and exported alongside traces and metrics, with `trace_id` / `span_id` populated from the active span. Two new settings: `CLOUD_EXPORT_LOGS` (default `True`) and `CLOUD_LOG_LEVEL` (default `"INFO"`, accepts a level name or int). The root logger's effective level is widened upward to `CLOUD_LOG_LEVEL` when narrower so libraries using `getLogger(__name__)` reach the exporter; it is never narrowed. To prevent feedback loops under transport failure, the exporter ignores records from the `opentelemetry` namespace and from any OTel SDK exporter thread (`OtelBatchSpanRecordProcessor`, `OtelBatchLogRecordProcessor`, `OtelPeriodicExportingMetricReader`). Application urllib3 logs are exported normally. ([3937adee2153](https://github.com/dropseed/plain/commit/3937adee2153))
- Added a `LoggerProvider` collision check that mirrors the existing `TracerProvider` check, so `plain.cloud` will fail loudly with the "list before plain.observer" message if another package has already installed a logger provider. ([3937adee2153](https://github.com/dropseed/plain/commit/3937adee2153))

### Upgrade instructions

- No changes required. To opt out of log export, set `CLOUD_EXPORT_LOGS=False` (or `PLAIN_CLOUD_EXPORT_LOGS=false`). To raise/lower the severity floor, set `CLOUD_LOG_LEVEL` (e.g. `"WARNING"`).

## [0.2.0](https://github.com/dropseed/plain/releases/plain-connect@0.2.0) (2026-04-27)

### What's changed

- **Changed the default `CLOUD_EXPORT_URL` to `https://ingest.plainframework.com`** (was `https://plainframework.com/otel`). Projects relying on the default will now export to the dedicated ingest subdomain. ([e58c02eaab9e](https://github.com/dropseed/plain/commit/e58c02eaab9e))

### Upgrade instructions

- If you were depending on the previous default, set `PLAIN_CLOUD_EXPORT_URL=https://plainframework.com/otel` (or assign `CLOUD_EXPORT_URL` in `app/settings.py`) to keep the old endpoint. Otherwise no changes required.

## [0.1.5](https://github.com/dropseed/plain/releases/plain-connect@0.1.5) (2026-04-13)

### What's changed

- Removed redundant `atexit` shutdown registrations that duplicated the shutdown hooks already registered elsewhere. ([dfb2ce53cd5c](https://github.com/dropseed/plain/commit/dfb2ce53cd5c))

### Upgrade instructions

- No changes required.

## [0.1.4](https://github.com/dropseed/plain/releases/plain-connect@0.1.4) (2026-04-02)

### What's changed

- Switched metrics export to delta temporality for Counter, Histogram, and UpDownCounter. Each export now contains only the increment since the last collection, making server-side aggregation in ClickHouse straightforward. ([ab431cb5ffe6](https://github.com/dropseed/plain/commit/ab431cb5ffe6))

### Upgrade instructions

- No changes required.

## [0.1.3](https://github.com/dropseed/plain/releases/plain-connect@0.1.3) (2026-04-01)

### What's changed

- Added `CLOUD_EXPORT_ENABLED` setting (defaults to `True`) to allow disabling all OTEL reporting without removing the token. Set `PLAIN_CLOUD_EXPORT_ENABLED=false` to turn it off. ([e9c4d140b227](https://github.com/dropseed/plain/commit/e9c4d140b227))
- Raises `RuntimeError` if another tracer provider is already configured when plain.cloud initializes — ensures `plain.cloud` is listed before `plain.observer` in `INSTALLED_PACKAGES`. ([40252d96ce7d](https://github.com/dropseed/plain/commit/40252d96ce7d))

### Upgrade instructions

- No changes required.

## [0.1.2](https://github.com/dropseed/plain/releases/plain-connect@0.1.2) (2026-04-01)

### What's changed

- `CLOUD_EXPORT_URL` now defaults to `https://plainframework.com/otel` — no need to set it manually. Export is gated on `CLOUD_EXPORT_TOKEN` instead, so only one env var is needed to start pushing telemetry. ([fa711758acda](https://github.com/dropseed/plain/commit/fa711758acda))

### Upgrade instructions

- If you had `PLAIN_CLOUD_EXPORT_URL` set to `https://plainframework.com/otel`, you can remove it — that's now the default.
- If you relied on leaving `CLOUD_EXPORT_URL` empty to disable export, set `CLOUD_EXPORT_TOKEN` to empty instead (or just don't set it).

## [0.1.1](https://github.com/dropseed/plain/releases/plain-connect@0.1.1) (2026-04-01)

### What's changed

- Updated export endpoint URLs in docs and default settings from `plaincloud.com` to `plainframework.com/otel`. ([15bb896cdbe6](https://github.com/dropseed/plain/commit/15bb896cdbe6))

### Upgrade instructions

- If you have `PLAIN_CLOUD_EXPORT_URL` set to `https://ingest.plaincloud.com`, update it to `https://plainframework.com/otel`.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-connect@0.1.0) (2026-04-01)

### What's changed

- **Initial release.** Sets up OpenTelemetry TracerProvider and MeterProvider with OTLP HTTP exporters, pushing traces and metrics to Plain Cloud. Configure with `CLOUD_EXPORT_URL` and `CLOUD_EXPORT_TOKEN` settings. Includes head-based trace sampling via `CLOUD_TRACE_SAMPLE_RATE`. Inactive when `CLOUD_EXPORT_URL` is not set. Coexists with plain-observer — observer layers its sampler and span processor on top. ([e3971506cb](https://github.com/dropseed/plain/commit/e3971506cb))
