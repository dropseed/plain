# Enterprise Readiness

Features and signals that give enterprise customers confidence when running Plain self-hosted on-prem.

## Audit logging

The biggest gap. No audit log model, no model change tracking, no admin action logging. Observer tracks performance, not compliance.

Enterprise needs "who changed what, when" for:

- Admin actions (create/update/delete)
- Auth events (login, logout, failed login, password change)
- Sensitive data access

The _what to audit_ is app-specific, but the infrastructure belongs in the framework. A `plain-audit` package with:

- `AuditEntry` model: actor, action, target (content type + pk), timestamp, diff of changed fields
- Auto-logging from admin views
- Auth event logging (login/logout/failed)
- Optional decorator or mixin for custom views
- Immutable (no update/delete on the model)
- Retention policy setting for cleanup

Apps would then configure which models/views to audit and add any app-specific audit events.

Effort: medium. Impact: compliance checkbox, often a hard requirement.

## OTLP export from observer

Traces only go to the app's own database today. Enterprise ops teams use Jaeger/Tempo/Datadog/etc. Need:

- Built-in OTLP exporter configuration (endpoint URL setting)
- Docs on wiring up external APM tools
- Option to disable DB persistence when using external export

The OTEL foundation is already there — this is mostly configuration and documentation.

Effort: medium. Impact: plugs into existing monitoring stack.

## Rate limiting

No built-in rate limiting for login attempts or API endpoints. Common security review checkbox.

Could be middleware-based with configurable backends (in-memory for single-process, cache-based for multi-process). Framework provides the middleware; apps configure which endpoints and what limits.

Effort: small-medium. Impact: security review checkbox.

## 2FA/MFA

No multi-factor authentication support. Would need a new package or integration point for TOTP, WebAuthn, etc.

## Brute force protection

No account lockout, no failed login tracking, no CAPTCHA integration. Overlaps with rate limiting but is a distinct concern — rate limiting throttles requests, brute force protection tracks failed attempts per account.

## Distributed tracing

Observer stores traces locally in the app's database. No cross-service trace correlation. Overlaps with OTLP export — once traces can be exported, distributed tracing comes from the external backend.

## Prometheus metrics endpoint

No `/metrics` endpoint, no counters/gauges/histograms. No way for Prometheus to scrape application metrics.
