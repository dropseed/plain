---
depends_on:
  - metrics
  - auth-otel-user-context
---

# Enterprise Readiness

Features and signals that give enterprise customers confidence when running Plain self-hosted on-prem.

## Narrative

Plain is built on Django's battle-tested foundation (Instagram, Mozilla, NASA, Fortune 500 internal tools). The story is: a proven, enterprise-grade core with a modernized API surface. Not "a fork" — a successor.

## What already exists

**Health checks:** `HEALTHCHECK_PATH` responds at the event loop level before thread pool/middleware — won't false-positive under load. Since the server _is_ Plain (no separate web server in front), a response proves the framework initialized successfully. This matches what Rails 7.1+ (`/up`) and Laravel 11 (`/up`) do — simple "did the app boot" checks without DB verification. A separate DB-checking readiness probe is intentionally omitted: if the database hiccups, it would cause K8s to pull all pods from the Service simultaneously, escalating a minor blip into a full outage.

**Structured logging:** `LOG_FORMAT=json` outputs proper structured JSON with timestamps, levels, context fields, exceptions. Access logs respect the format. Stream splitting by level. Ready for Splunk/ELK/Datadog as-is.

**Security:**

- Modern CSRF via `Sec-Fetch-Site` headers
- CSP nonce generation per-request
- Secure cookie defaults (HttpOnly, Secure, SameSite=Lax)
- Session cycling on login (prevents fixation)
- Password hash verification on every request
- HTTPS redirect enforcement
- Preflight deployment checks (`plain preflight --deploy`)
- `plain-scan` security audit suite (CSP, HSTS, CORS, TLS, cookies, etc.)
- SECRET_KEY validation and rotation support

**Observability:** OpenTelemetry-based tracing with rich span data (DB queries with SQL, code location, request attributes). Built on standard OTEL APIs.

## What's missing

### 1. ~~Security policy (SECURITY.md)~~ — done

Shipped in repo root. Covers disclosure process (GitHub advisory + email), 48h acknowledgment SLA, supported versions.

### 2. Audit logging — framework

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

### 3. OTLP export from observer — framework

Traces only go to the app's own database today. Enterprise ops teams use Jaeger/Tempo/Datadog/etc. Need:

- Built-in OTLP exporter configuration (endpoint URL setting)
- Docs on wiring up external APM tools
- Option to disable DB persistence when using external export

The OTEL foundation is already there — this is mostly configuration and documentation.

Effort: medium. Impact: plugs into existing monitoring stack.

### 4. Rate limiting — framework

No built-in rate limiting for login attempts or API endpoints. Common security review checkbox.

Could be middleware-based with configurable backends (in-memory for single-process, cache-based for multi-process). Framework provides the middleware; apps configure which endpoints and what limits.

Effort: small-medium. Impact: security review checkbox.

## Priority order

| #     | Item                              | Level               | Effort       | Blocks                 |
| ----- | --------------------------------- | ------------------- | ------------ | ---------------------- |
| ~~1~~ | ~~Security policy (SECURITY.md)~~ | ~~Framework + App~~ | ~~Tiny~~     | ~~Done~~               |
| 2     | Audit logging                     | Framework           | Medium       | Compliance review      |
| 3     | OTLP export                       | Framework           | Medium       | Monitoring integration |
| 4     | Rate limiting                     | Framework           | Small-Medium | Security review        |

SBOM generation removed — this is an app/deployment concern. Tools like Syft and pip-audit already handle it; no framework wrapper needed.
