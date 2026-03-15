---
labels:
  - plain.http
  - plain.server
  - plain.logs
  - plain.preflight
  - plain-observer
  - plain-admin
  - plain-auth
  - plain-scan
  - plain-sessions
  - plain-passwords
related:
  - enterprise-readiness
---

# Enterprise Readiness — Research Notes

Detailed inventory of what already exists across the framework, compiled while scoping the enterprise readiness proposal.

## Health checks

The `HEALTHCHECK_PATH` implementation is notably good:

- Responds on the asyncio event loop **before** thread pool dispatch — won't false-positive when workers are saturated
- Raw HTTP response with minimal headers (no middleware overhead)
- Implemented for both H1 (`plain/server/http/h1.py:35-41,596-600`) and H2 (`plain/server/http/h2.py:329,417-438`)
- Worker encodes the path to bytes at init for fast comparison (`plain/server/workers/worker.py:91-94`)
- Full test suite including integration tests with real TCP server (`tests/test_healthcheck_server.py`)
- Load tested alongside normal traffic (`tools/server-worker-test.py:435-441`)

## Logging infrastructure

`plain/logs/` is a complete structured logging system:

| Component                    | File            | Purpose                                   |
| ---------------------------- | --------------- | ----------------------------------------- |
| `AppLogger`                  | `app.py`        | Custom logger with context dict support   |
| `KeyValueFormatter`          | `formatters.py` | `[LEVEL] message key1=value1 key2=value2` |
| `JSONFormatter`              | `formatters.py` | Single-line JSON with all context merged  |
| `DebugInfoFilter`            | `filters.py`    | Routes DEBUG/INFO to stdout               |
| `WarningErrorCriticalFilter` | `filters.py`    | Routes WARNING+ to stderr                 |
| `DebugMode`                  | `debug.py`      | Context manager for temporary DEBUG       |
| `configure_logging()`        | `configure.py`  | Setup with stream splitting               |

**Settings:**

- `LOG_FORMAT` — `"keyvalue"` (default) or `"json"` (env: `PLAIN_LOG_FORMAT`)
- `LOG_LEVEL` — default `INFO` (env: `PLAIN_LOG_LEVEL`)
- `FRAMEWORK_LOG_LEVEL` — default `INFO` (env: `PLAIN_FRAMEWORK_LOG_LEVEL`)
- `LOG_STREAM` — `"split"` (default), `"stdout"`, or `"stderr"`

**Access logging** (`server/accesslog.py`):

- Separate logger (`plain.server.access`), always stdout
- Respects `LOG_FORMAT` setting
- Controlled by `SERVER_ACCESS_LOG` (default: enabled)
- Fields customizable via `SERVER_ACCESS_LOG_FIELDS`

**Context support:**

- Persistent context via `app_logger.context` dict
- Temporary context via `include_context()` context manager
- Both formatters extract and render context automatically

## Security features inventory

### HTTP security headers (global_settings.py + DefaultHeadersMiddleware)

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: same-origin`
- `Cross-Origin-Opener-Policy: same-origin`
- Dynamic placeholder formatting for CSP nonces

### CSRF (csrf/middleware.py)

- Primary defense: `Sec-Fetch-Site` browser metadata headers
- Fallback: Origin vs Host validation for older browsers
- `CSRF_TRUSTED_ORIGINS` whitelist
- `CSRF_EXEMPT_PATHS` regex patterns
- Same-origin (not same-site) — subdomains treated as different origins
- References Filippo Valsorda's 2025 CSRF research

### CSP

- Per-request nonce via `request.csp_nonce` (16 bytes, URL-safe base64)
- Configured through `DEFAULT_RESPONSE_HEADERS`
- `plain-scan` audits CSP with 17+ sub-checks (unsafe-inline, unsafe-eval, nonce length, known bypass domains, deprecated directives)

### Session security

- Database-backed (not cookie-based)
- Defaults: `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`
- 2-week expiration after last modification
- Session cycling on login (prevents fixation)
- Password hash verification on every request — session invalidated on password change
- `update_session_auth_hash()` for explicit hash refresh
- Session key cycling for secret key rotation with fallback

### Password security

- PBKDF2-SHA256 default (configurable via `PASSWORD_HASHERS`)
- Auto hash upgrade when algorithm changes
- Validators: min length (8), 20k+ common password list, numeric-only rejection

### Request limits

- `DATA_UPLOAD_MAX_MEMORY_SIZE`: 2.5 MB
- `FILE_UPLOAD_MAX_MEMORY_SIZE`: 2.5 MB
- `DATA_UPLOAD_MAX_NUMBER_FIELDS`: 1000
- `DATA_UPLOAD_MAX_NUMBER_FILES`: 100

### HTTPS

- `HTTPS_REDIRECT_ENABLED`: True (default)
- `HTTPS_PROXY_HEADER` for detection behind load balancers

### Secret key management

- Preflight validates: min 50 chars, at least 5 unique chars
- `SECRET_KEY_FALLBACKS` for rotation with HMAC verification

### Preflight deployment checks (`plain preflight --deploy`)

- `security.secret_key` — validates strength
- `security.secret_key_fallbacks` — validates fallback keys
- `security.debug` — ensures DEBUG=False
- `security.allowed_hosts` — validates not empty

### plain-scan audit suite

Full HTTP security audits for any URL:

- CSP (17+ checks including bypass domain detection)
- HSTS
- Frame options / frame-ancestors
- Cookie flags (Secure, HttpOnly, SameSite)
- CORS (wildcard+credentials, null origins)
- TLS (certificate expiry, protocol)
- Content-Type options
- Referrer policy
- Redirect chain analysis

## Observability (plain-observer)

### Architecture

- Built on OpenTelemetry SDK (`opentelemetry-api >= 1.34.1`, `opentelemetry-sdk >= 1.34.1`)
- Core components: `ObserverSampler`, `ObserverSpanProcessor`, `ObserverCombinedSampler`
- Models: `Trace`, `Span`, `Log` persisted to PostgreSQL

### What's instrumented

- **HTTP requests** (`internal/handlers/base.py`): request ID, method, path, scheme, query string, route info, response status, errors
- **Database queries** (`plain-models/plain/models/otel.py`): operation type, table name, SQL text, parameterized values, source code location (file/line/function/stacktrace in DEBUG), network peer info
- **Background jobs** (`plain-jobs`): job parameters, errors, linked to originating request trace

### Modes

- **Summary**: In-memory trace collection, no DB writes (1-week cookie)
- **Persist**: Full DB persistence with logs + spans (1-day cookie)
- **Disabled**: Explicitly off
- Controlled via signed cookies for per-user toggling

### Access

- Web UI at `/observer/traces/`
- Admin integration with searchable list views
- Toolbar panel (query count, duplicates, duration)
- CLI: `plain observer traces`, `trace <id>`, `spans`, `clear`
- JSON export (`--json`)

### OTEL context propagation

- Properly propagates across async/sync boundaries in the server
- Parent-based sampling honors upstream decisions

## Notable gaps beyond the proposal

These are lower priority but worth knowing about:

- **No 2FA/MFA** — would need custom implementation or a new package
- **No concurrent session management** — can't "log out all other sessions" or limit session count
- **No field-level encryption** — see `models-encrypted-field.md` proposal
- **No brute force protection** — no account lockout, no failed login tracking, no CAPTCHA
- **No distributed tracing** — observer stores traces locally, no cross-service correlation
- **No Prometheus metrics endpoint** — no `/metrics`, no counters/gauges/histograms
- **No admin action logging** — admin create/update/delete views don't record who did what
- **Observer is DB-centric** — fine for dev, but inflates production database and doesn't scale for high traffic (100-trace limit in settings)
