# plain changelog

## [0.132.0](https://github.com/dropseed/plain/releases/plain@0.132.0) (2026-04-13)

### What's changed

- **Removed `AUTH_USER_MODEL` setting.** The User model is now fixed at `app.users.models.User` — a required convention, not a configurable setting. Code that used `SettingsReference("AUTH_USER_MODEL")` or imported from a user-configured location must be updated. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- **Removed `plain.runtime.SettingsReference`.** It was only used to defer resolution of `AUTH_USER_MODEL` in migrations, which no longer exists. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- **Made `FormView` generic over its form type.** `FormView[MyForm]` now types `self.form` and related methods with the concrete form class. ([8dbe9e413d30](https://github.com/dropseed/plain/commit/8dbe9e413d30))
- **Server now closes listener sockets immediately on SIGTERM.** Prevents new connections from landing on a worker that's about to exit, which could cause H13 errors on Heroku and similar platforms. ([5fb7c2fb482f](https://github.com/dropseed/plain/commit/5fb7c2fb482f))
- Updated `plain request --user` to resolve users via `app.users.models.User` instead of `get_user_model()`. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- Migrated type suppression comments to `ty: ignore` and upgraded the ty checker to 0.0.29. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- Move your User model to `app/users/models.py` (package label `users`, class name `User`) if it isn't already there. Remove `AUTH_USER_MODEL` from `settings.py`.
- If you referenced `plain.runtime.SettingsReference`, remove the usage — the class no longer exists.

## [0.131.3](https://github.com/dropseed/plain/releases/plain@0.131.3) (2026-04-05)

### What's changed

- **Fixed OTel baggage data leak.** Request cookies and headers were passed to the observer sampler via OTel baggage, which propagates to downstream services. Any instrumented outbound HTTP client would have serialized cookies and auth tokens into the `baggage:` header. Now uses process-local context values instead. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **HTTP server span name no longer includes raw URL path.** Span names start as just the HTTP method (e.g. `GET`) and are updated to `GET /users/<id>/` after URL resolution. Previously, the raw path was used from the start, causing high-cardinality span names for 404s and middleware failures. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Removed `url.full` from HTTP server spans.** The HTTP semconv doesn't define `url.full` for server spans — `url.path` and `url.query` are already set separately. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Added recommended HTTP server span attributes.** `server.address`, `server.port`, `client.address`, and `user_agent.original` are now set on HTTP server spans. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Unknown HTTP methods normalized to `_OTHER`.** Per the HTTP semconv, unrecognized methods are now set to `_OTHER` with the original value in `http.request.method_original`. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Added `error.type` to HTTP server spans.** Set to the exception class name on 5xx with an exception, or the status code string for 5xx without one. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Added `network.protocol.name` to `http.server.request.duration` metric.** ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Removed `set_status(OK)` from HTTP server span.** Per the OTel spec, instrumentation libraries should leave span status as Unset on success. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Template tracer renamed from `plain` to `plain.templates`.** ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Template `code.namespace` replaced with fully-qualified `code.function.name`.** Uses the stable semconv attribute. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Added `plain.utils.otel` module** with `format_exception_type()` helper shared across packages. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))

### Upgrade instructions

- No changes required.

## [0.131.2](https://github.com/dropseed/plain/releases/plain@0.131.2) (2026-04-03)

### What's changed

- **OTel span status and `error.type` metric now only flag 5xx responses as errors.** Previously, 4xx responses were marked as `StatusCode.ERROR` on server spans and included `error.type` in request duration metrics. Per the OpenTelemetry HTTP semantic conventions, only 5xx responses should be treated as server errors — 4xx is expected behavior from the server's perspective. ([1f058a6119ce](https://github.com/dropseed/plain/commit/1f058a6119ce))

### Upgrade instructions

- No changes required.

## [0.131.1](https://github.com/dropseed/plain/releases/plain@0.131.1) (2026-04-02)

### What's changed

- **`ServerSentEventsView.get()` is now sync.** The `get()` method was unnecessarily `async` — it only constructs an `AsyncStreamingResponse` without awaiting anything. Making it sync fixes compatibility with `AuthView` and other view mixins that override `get_response()`, which previously received a coroutine instead of a response object. ([890d0d6ddb5a](https://github.com/dropseed/plain/commit/890d0d6ddb5a))

### Upgrade instructions

- If you override `get()` on a `ServerSentEventsView` subclass with `async def get(self)`, change it to `def get(self)`. The `stream()` method remains async — no changes needed there.

## [0.131.0](https://github.com/dropseed/plain/releases/plain@0.131.0) (2026-04-01)

### What's changed

- **Added `http.server.request.duration` OTel histogram to the request handler.** Records request duration in seconds with standard HTTP semantic convention attributes (`http.request.method`, `http.response.status_code`, `url.scheme`, `http.route`, `error.type`). ([c40bfd42bdd8](https://github.com/dropseed/plain/commit/c40bfd42bdd8))

### Upgrade instructions

- No changes required.

## [0.130.2](https://github.com/dropseed/plain/releases/plain@0.130.2) (2026-04-01)

### What's changed

- **`plain request --data` now auto-detects content type.** If `--content-type` is not specified, JSON data (starting with `{` or `[`) is sent as `application/json`, otherwise as `application/x-www-form-urlencoded`. ([0af889455ffa](https://github.com/dropseed/plain/commit/0af889455ffa))

### Upgrade instructions

- No changes required.

## [0.130.1](https://github.com/dropseed/plain/releases/plain@0.130.1) (2026-03-29)

### What's changed

- Indented preflight check lines and summary under the "Running preflight checks..." header for readability in environments without ANSI colors. ([b6b494dcc698](https://github.com/dropseed/plain/commit/b6b494dcc698))

### Upgrade instructions

- No changes required.

## [0.130.0](https://github.com/dropseed/plain/releases/plain@0.130.0) (2026-03-29)

### What's changed

- **`plain check` now uses `postgres sync --check`** instead of separate `migrate --check` and `makemigrations --check` calls. This validates migrations, pending model changes, and convergence in a single step. ([13bd4b963394](https://github.com/dropseed/plain/commit/13bd4b963394))
- Removed the top-level `makemigrations` and `migrate` shortcut commands. Use `migrations create` and `migrations apply` (under `plain postgres`), or `plain postgres sync` for the combined workflow. ([adf021688bf3](https://github.com/dropseed/plain/commit/adf021688bf3), [b026895edc4c](https://github.com/dropseed/plain/commit/b026895edc4c))

### Upgrade instructions

- Replace `plain migrate` with `plain postgres sync` and `plain makemigrations` with `plain migrations create` in scripts and CI. Requires `plain-postgres>=0.91.0`.

## [0.129.0](https://github.com/dropseed/plain/releases/plain@0.129.0) (2026-03-27)

### What's changed

- **Renamed `forms.CharField` to `forms.TextField`** — all subclasses (`EmailField`, `URLField`, `UUIDField`, `JSONField`, `RegexField`) now extend `TextField` ([4e29f5d6cade](https://github.com/dropseed/plain/commit/4e29f5d6cade))
- **Replaced `**kwargs`with explicit parameters in Response classes** —`Response`, `StreamingResponse`, `AsyncStreamingResponse`, `FileResponse`, `RedirectResponse`, `NotModifiedResponse`, `NotAllowedResponse`, and `JsonResponse` now declare all parameters explicitly ([7d1cb9af3a06](https://github.com/dropseed/plain/commit/7d1cb9af3a06))
- **Removed `signing.dumps()` and `signing.loads()`** — use `TimestampSigner(salt=...).sign_object()` / `.unsign_object()` or `Signer` directly ([99b0e57bc175](https://github.com/dropseed/plain/commit/99b0e57bc175))
- Disabled worker recycling in reload mode — file-change restarts already recycle workers, so `max_requests` retirement was causing unnecessary extra restart cycles during development ([8eb9c6da485e](https://github.com/dropseed/plain/commit/8eb9c6da485e))
- Added `TYPE_CHECKING` stubs for View handler methods (`get`, `post`, `put`, `patch`, `delete`, `head`, `trace`) to improve IDE autocomplete and type checking ([ca7ee03424d1](https://github.com/dropseed/plain/commit/ca7ee03424d1))

### Upgrade instructions

- Rename `forms.CharField` to `forms.TextField` in all form definitions.
- Replace `signing.dumps(obj, salt=..., ...)` with `TimestampSigner(salt=...).sign_object(obj, ...)` and `signing.loads(s, salt=..., ...)` with `TimestampSigner(salt=...).unsign_object(s, ...)`.
- If you pass `**kwargs` to Response subclasses, switch to named keyword arguments (`content_type=`, `status_code=`, `headers=`, etc.).

## [0.128.0](https://github.com/dropseed/plain/releases/plain@0.128.0) (2026-03-26)

### What's changed

- **Zero-downtime worker recycling** — when a worker hits `SERVER_MAX_REQUESTS`, it now signals for a replacement via a shared-memory flag and keeps serving traffic. The arbiter pre-spawns a replacement and only shuts down the retiring worker once the replacement is heartbeating, eliminating the capacity gap that previously occurred during worker recycling. ([9eaeded599fa](https://github.com/dropseed/plain/commit/9eaeded599fa))

### Upgrade instructions

- No changes required.

## [0.127.2](https://github.com/dropseed/plain/releases/plain@0.127.2) (2026-03-24)

### What's changed

- Fixed `post()` data type annotation in test client (`RequestFactory` and `Client`) to accept `Any` instead of `dict[str, Any] | None`, allowing JSON payloads and other data types ([a67018f94cfb](https://github.com/dropseed/plain/commit/a67018f94cfb))
- Updated agent rules and skill descriptions ([669e52eda37d](https://github.com/dropseed/plain/commit/669e52eda37d), [bdff05dfb9f6](https://github.com/dropseed/plain/commit/bdff05dfb9f6), [1be549a7fd31](https://github.com/dropseed/plain/commit/1be549a7fd31))

### Upgrade instructions

- No changes required.

## [0.127.1](https://github.com/dropseed/plain/releases/plain@0.127.1) (2026-03-22)

### What's changed

- Added `plain-portal` to workspace, package list, and `plain docs` registry ([7c782e15a962](https://github.com/dropseed/plain/commit/7c782e15a962))
- Consistent format for server worker log messages ([905c4f2ea051](https://github.com/dropseed/plain/commit/905c4f2ea051))

### Upgrade instructions

- No changes required.

## [0.127.0](https://github.com/dropseed/plain/releases/plain@0.127.0) (2026-03-20)

### What's changed

- **Container-aware system metrics in `plain.utils.os`** — added `get_rss_bytes()`, `get_memory_usage()`, and `get_process_cpu_percent()` helpers that work inside cgroups v1/v2 containers. Also added cgroup v1 CPU quota support to `get_cpu_count()` ([40482feb2b](https://github.com/dropseed/plain/commit/40482feb2b))
- **Test client now creates OTel spans** — `plain.test.Client` wraps each request in a server span, so observer traces are captured during tests ([aa54f27d95](https://github.com/dropseed/plain/commit/aa54f27d95))
- **`plain request --user` accepts email addresses** — in addition to user IDs, with a clearer error when `plain-auth` is not installed ([aa54f27d95](https://github.com/dropseed/plain/commit/aa54f27d95))
- Updated the plain-upgrade skill to include a "plain agent install" step ([5cae05a696](https://github.com/dropseed/plain/commit/5cae05a696))

### Upgrade instructions

- No changes required.

## [0.126.0](https://github.com/dropseed/plain/releases/plain@0.126.0) (2026-03-20)

### What's changed

- **Worker recycling** — workers now gracefully restart after a configurable number of requests to prevent memory accumulation from fragmentation, C extension leaks, or unbounded caches. Controlled by new `SERVER_MAX_REQUESTS` (default 1000, 0 to disable) and `SERVER_MAX_REQUESTS_JITTER` (default 100) settings. Both HTTP/1.1 requests and HTTP/2 streams count toward the limit ([e953f62609](https://github.com/dropseed/plain/commit/e953f62609))
- **Structured logging throughout the framework** — all `plain.*` loggers now use the same key-value / JSON formatters as `app_logger` instead of bare `[LEVEL] message` format. Log messages use stable, greppable sentence fragments with variable data passed as structured `extra={}` fields rather than `%s` interpolation ([75a8b60c91](https://github.com/dropseed/plain/commit/75a8b60c91))
- **`get_framework_logger()` factory** — new public function in `plain.logs` that auto-derives logger names from the caller's module (e.g. `plain.server.workers.entry` becomes `plain.server`), replacing scattered `logging.getLogger("plain.xxx")` calls across the codebase ([2e25cae784](https://github.com/dropseed/plain/commit/2e25cae784))
- **`AppLogger` renamed to `PlainLogger`** — the logger class in `plain.logs` has been renamed and moved from `app.py` to `logger.py`. The `app_logger` instance and its API are unchanged. A new `exception()` method was added to support `context={}` on exception logs ([b79829ddbb](https://github.com/dropseed/plain/commit/b79829ddbb))
- **Flat extra for structured formatters** — `PlainLogger._log()` now merges persistent context, `extra`, and per-call `context` into flat top-level `LogRecord` attributes instead of nesting under `extra["context"]`. The `KeyValueFormatter` and `JSONFormatter` extract context by diffing against standard `LogRecord` attributes, so both `app_logger` and standard `plain.*` loggers produce identical structured output ([5148b2bc31](https://github.com/dropseed/plain/commit/5148b2bc31))
- **Response body size in traces** — the `http.response.body.size` OpenTelemetry attribute is now set on server spans for non-streaming responses, making response sizes visible in observer traces and the toolbar ([46f981ff80](https://github.com/dropseed/plain/commit/46f981ff80))
- **Cgroup-aware CPU count shared via `plain.utils.os`** — the `get_cpu_count()` helper was moved from the server CLI to `plain.utils.os` so the jobs worker can also use it for container-aware process counts ([aa0e57b7eb](https://github.com/dropseed/plain/commit/aa0e57b7eb))

### Upgrade instructions

- If you subclassed or imported `AppLogger` directly, update to `PlainLogger` (import path changed from `plain.logs.app` to `plain.logs.logger`).
- If you relied on `extra["context"]` being a nested dict on log records from `app_logger`, note that context keys are now flat top-level attributes on the `LogRecord`. Standard `extra={}` usage and `context={}` on `app_logger` calls are unaffected.
- Review any custom log parsing that expected `[LEVEL] message` format from `plain.*` loggers — they now use the same formatter as `app_logger` (key-value or JSON depending on `APP_LOG_FORMAT`).

## [0.125.0](https://github.com/dropseed/plain/releases/plain@0.125.0) (2026-03-19)

### What's changed

- **`plain memory baseline`** — new command that measures per-package memory cost at worker boot time, showing which dependencies are heaviest. Runs in an isolated subprocess for accurate measurements ([4b747665fc2a](https://github.com/dropseed/plain/commit/4b747665fc2a))
- **`plain memory leaks`** — new command that detects memory leaks on a running server. Uses a three-phase tracemalloc approach (snapshots A, B, C) and reports only allocations that grew in both halves, filtering one-time initialization noise. Includes auto-stop safety timeout, atomic file writes, and current RSS on Linux via `/proc/self/statm` ([cdd7b2def319](https://github.com/dropseed/plain/commit/cdd7b2def319))
- Server arbiter now handles `SIGUSR1` to forward memory recording signals to all workers ([cdd7b2def319](https://github.com/dropseed/plain/commit/cdd7b2def319))

### Upgrade instructions

- No changes required.

## [0.124.1](https://github.com/dropseed/plain/releases/plain@0.124.1) (2026-03-16)

### What's changed

- Added `/plain-guide` skill for researching framework questions using `plain docs` and source code ([16597aa560af](https://github.com/dropseed/plain/commit/16597aa560af))
- `plain docs --search` now supports regex patterns instead of only literal string matching ([1b494cbe7d8f](https://github.com/dropseed/plain/commit/1b494cbe7d8f))

### Upgrade instructions

- No changes required.

## [0.124.0](https://github.com/dropseed/plain/releases/plain@0.124.0) (2026-03-12)

### What's changed

- Updated all references from `plain.models` to `plain.postgres` across views, CLI docs, registry docstrings, README doc links, and agent rules.

### Upgrade instructions

- Update imports: `from plain.models` to `from plain.postgres`, `from plain import models` to `from plain import postgres`.

## [0.123.4](https://github.com/dropseed/plain/releases/plain@0.123.4) (2026-03-12)

### What's changed

- **Read cgroup v2 CPU quota for accurate container worker count** — `os.process_cpu_count()` only checks `sched_getaffinity`, not cgroup CPU quotas, so containers still saw the host CPU count. Now reads `/proc/self/cgroup` to resolve the process's cgroup path, then parses `cpu.max` for the actual quota. Uses ceiling division so fractional vCPUs (e.g. 1.5) round up to 2 workers. Silently falls through on non-Linux systems ([32785b4634e8](https://github.com/dropseed/plain/commit/32785b4634e8))

### Upgrade instructions

- No changes required.

## [0.123.3](https://github.com/dropseed/plain/releases/plain@0.123.3) (2026-03-12)

### What's changed

- **Fix auto worker count in Docker/cgroup environments** — replaced `os.cpu_count()` with `os.process_cpu_count()` (Python 3.13+) for cgroup-aware CPU detection. Previously, containers would see the host's CPU count instead of their allocated limit, spawning far too many workers (e.g. 48 on a 2 vCPU container) ([c1e2c186c3aa](https://github.com/dropseed/plain/commit/c1e2c186c3aa))

### Upgrade instructions

- No changes required.

## [0.123.2](https://github.com/dropseed/plain/releases/plain@0.123.2) (2026-03-12)

### What's changed

- **Server startup log now includes workers and threads** — the startup message shows `workers=N threads=N` so you can confirm the server configuration at a glance ([e63d9f90520c](https://github.com/dropseed/plain/commit/e63d9f90520c))
- **H2 max concurrent streams setting registered with default of 100** — `SERVER_H2_MAX_CONCURRENT_STREAMS` is now a proper setting with a default value instead of using `getattr` with a fallback ([e72a4006515f](https://github.com/dropseed/plain/commit/e72a4006515f))

### Upgrade instructions

- No changes required.

## [0.123.1](https://github.com/dropseed/plain/releases/plain@0.123.1) (2026-03-12)

### What's changed

- **Health check moved from middleware to server event loop** — the `HEALTHCHECK_PATH` endpoint now responds directly on the async event loop with a raw `200 OK` before the request reaches the thread pool or any middleware. This means health checks continue to work even when the thread pool is fully saturated. Supports both HTTP/1.1 and HTTP/2 connections ([ef8f020a86dc](https://github.com/dropseed/plain/commit/ef8f020a86dc))
- Removed `HealthcheckMiddleware` — no longer needed since the server handles health checks directly ([ef8f020a86dc](https://github.com/dropseed/plain/commit/ef8f020a86dc))

### Upgrade instructions

- No changes required.

## [0.123.0](https://github.com/dropseed/plain/releases/plain@0.123.0) (2026-03-11)

### What's changed

- **Open redirect protection for `RedirectResponse`** — external URLs are now rejected by default. Pass `allow_external=True` to explicitly allow redirects to external hosts (OAuth, CDN, etc.). Detects scheme-based URLs (`http://`, `https://`, `ftp://`), protocol-relative (`//`), and backslash variants (`/\`, `\\`) with whitespace stripping to prevent bypass attacks ([5edfb2bedf90](https://github.com/dropseed/plain/commit/5edfb2bedf90))
- **`RedirectView.allow_external` attribute** — class-based redirect views now support `allow_external = True` for views that intentionally redirect to external URLs ([5edfb2bedf90](https://github.com/dropseed/plain/commit/5edfb2bedf90))

### Upgrade instructions

- If your code passes external URLs to `RedirectResponse` (e.g., OAuth providers, CDN URLs, SSO login pages), add `allow_external=True`:

    ```python
    # Before
    RedirectResponse("https://example.com/callback")

    # After
    RedirectResponse("https://example.com/callback", allow_external=True)
    ```

- For `RedirectView` subclasses that redirect externally, set `allow_external = True` on the class.
- Relative paths, query-only URLs, and other internal redirects continue to work without changes.

## [0.122.1](https://github.com/dropseed/plain/releases/plain@0.122.1) (2026-03-11)

### What's changed

- Fixed `is_bound` for forms with no fields (e.g., delete confirmation forms) — empty POST requests produced a falsy `QueryDict`, causing the form to never validate. `is_bound` now checks the request method instead of data truthiness ([f630b3b5fb22](https://github.com/dropseed/plain/commit/f630b3b5fb22))

### Upgrade instructions

- No changes required.

## [0.122.0](https://github.com/dropseed/plain/releases/plain@0.122.0) (2026-03-10)

### What's changed

- **`Secret` is now type-transparent** — `Secret[str]` is a type alias for `Annotated[str, _SecretMarker()]`, so type checkers see the underlying type directly. No more `type: ignore` comments needed on default values ([a90197b95315](https://github.com/dropseed/plain/commit/a90197b95315), [997afd9a558f](https://github.com/dropseed/plain/commit/997afd9a558f))
- **`TYPE_CHECKING` ignored in settings modules** — settings loading now skips `TYPE_CHECKING` (and other uppercase non-setting names) so you can use `from __future__ import annotations` and `if TYPE_CHECKING:` blocks in settings files without triggering duplicate-setting errors ([f20869e0bd2b](https://github.com/dropseed/plain/commit/f20869e0bd2b))
- Adopted PEP 695 type parameter syntax (`def foo[T]()` instead of `TypeVar`) across the codebase ([aa5b2db6e8ed](https://github.com/dropseed/plain/commit/aa5b2db6e8ed))

### Upgrade instructions

- If you previously had `type: ignore[assignment]` comments on `Secret` default values, you can remove them.
- No other changes required.

## [0.121.2](https://github.com/dropseed/plain/releases/plain@0.121.2) (2026-03-10)

### What's changed

- Added prescriptive "After making code changes" section to AI rules with `plain check` and `plain request` guidance ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))
- Distributed Django differences into package-specific rules (plain-models, plain-templates) instead of one monolithic list ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))
- Added `request.query_params`, `request.form_data`, `request.json_data`, `request.files` to Django differences ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))

### Upgrade instructions

- No changes required.

## [0.121.1](https://github.com/dropseed/plain/releases/plain@0.121.1) (2026-03-10)

### What's changed

- **Worker SIGTERM exits logged at info instead of error** — during graceful shutdown (e.g. Heroku deploy), workers exit with SIGTERM which is expected behavior. These are now logged at `info` level instead of `error`, preventing false alerts in error tracking ([1c3908d27aea](https://github.com/dropseed/plain/commit/1c3908d27aea))
- **Removed duplicate log messages for signal-killed workers** — workers killed by a signal previously produced two error log lines (generic exit code + signal name). Now only the more descriptive signal-specific message is logged ([1c3908d27aea](https://github.com/dropseed/plain/commit/1c3908d27aea))
- **Removed stack traces from intentional 4xx exception logging** — `PermissionDenied`, `MultiPartParserError`, and `BadRequestError400` exceptions no longer include `exc_info` in their log entries, reducing noise in error tracking ([c395232acdb9](https://github.com/dropseed/plain/commit/c395232acdb9))
- **Handle asyncio `ConnectionResetError` without errno** — asyncio's `_drain_helper` raises `ConnectionResetError('Connection lost')` without an errno, which bypassed the existing errno-based check. Now caught explicitly before the `OSError` errno check ([b623d4f78667](https://github.com/dropseed/plain/commit/b623d4f78667))
- Removed `type: ignore` comments across multiple modules with proper type fixes ([cda461b1b4f6](https://github.com/dropseed/plain/commit/cda461b1b4f6), [f56c6454b164](https://github.com/dropseed/plain/commit/f56c6454b164))

### Upgrade instructions

- No changes required.

## [0.121.0](https://github.com/dropseed/plain/releases/plain@0.121.0) (2026-03-09)

### What's changed

- **Replaced `threading.local()` with `ContextVar` for async compatibility** — timezone activation (`plain.utils.timezone`) and URL resolver population tracking now use `ContextVar` instead of `threading.local()`, making them safe for use in async contexts where multiple coroutines share a thread ([e5c4073cafbc](https://github.com/dropseed/plain/commit/e5c4073cafbc))
- **Graceful handling of client disconnects** — the server now catches `OSError` during keepalive waits (e.g. client TCP reset) and `ConnectionError` during connection handling, preventing noisy tracebacks from abrupt client disconnects ([e3aee49b32ac](https://github.com/dropseed/plain/commit/e3aee49b32ac))
- Updated `BaseHandler._run_in_executor` to propagate only the OpenTelemetry span context into executor threads, intentionally leaving DB connection ContextVars on their native thread context so connections persist across requests honoring `CONN_MAX_AGE` ([cc2469b1260a](https://github.com/dropseed/plain/commit/cc2469b1260a))

### Upgrade instructions

- No changes required.

## [0.120.1](https://github.com/dropseed/plain/releases/plain@0.120.1) (2026-03-08)

### What's changed

- **Simplified TLS handling using `asyncio.start_server(ssl=...)`** — TLS is now handled at connection accept time by asyncio instead of a manual two-step process (accept raw socket, then handshake). This eliminates the `_async_tls_handshake` method, the `handed_off` flag, and all raw socket I/O fallback paths. `Connection` now always receives `asyncio.StreamReader`/`StreamWriter` instead of a raw socket, removing dual-path code in `recv`, `sendall`, `wait_readable`, `close`, and `Response._async_send` ([c1e172eec835](https://github.com/dropseed/plain/commit/c1e172eec835))
- Removed `RequestParser`, `SocketUnreader`, `IterUnreader`, and several raw socket utility functions (`close`, `write`, `write_chunk`, `write_nonblock`, `async_recv`, `async_sendall`, `has_fileno`, `ssl_wrap_socket`) that are no longer needed ([c1e172eec835](https://github.com/dropseed/plain/commit/c1e172eec835))
- Removed synchronous `Response` write methods (`send_headers`, `write`, `sendfile`, `write_file`, `write_response`, `close`) and the `SERVER_SENDFILE` setting — all response writing now uses the async path ([c1e172eec835](https://github.com/dropseed/plain/commit/c1e172eec835))
- Connection backpressure now uses `asyncio.Semaphore` instead of a manual `asyncio.Event` with count checks ([c1e172eec835](https://github.com/dropseed/plain/commit/c1e172eec835))

### Upgrade instructions

- No changes required.

## [0.120.0](https://github.com/dropseed/plain/releases/plain@0.120.0) (2026-03-07)

### What's changed

- **Stalled thread pool detection in worker heartbeat** — the worker now submits a no-op to the thread pool during each heartbeat cycle and waits for it to complete within the timeout window. If the thread pool is stalled (all threads blocked), the heartbeat stops, causing the arbiter to kill and restart the worker automatically ([ce09f41a9db5](https://github.com/dropseed/plain/commit/ce09f41a9db5))

### Upgrade instructions

- No changes required.

## [0.119.0](https://github.com/dropseed/plain/releases/plain@0.119.0) (2026-03-07)

### What's changed

- **Removed `url_args` and positional URL arguments** — views no longer receive positional URL arguments via `self.url_args`. All URL parameters are now keyword-only via `self.url_kwargs`. `reverse()` and `reverse_absolute()` no longer accept `*args` — use keyword arguments instead. `RegexPattern` now rejects unnamed capture groups and requires named groups (`(?P<name>...)`) ([6eecc35ff197](https://github.com/dropseed/plain/commit/6eecc35ff197))
- **Server I/O moved to async event loop** — all network I/O (TLS handshakes, reading requests, writing responses, keep-alive) now runs on the asyncio event loop. The thread pool is reserved exclusively for application code (middleware and views). This improves connection handling efficiency and eliminates H2 reader threads ([322fd51cf206](https://github.com/dropseed/plain/commit/322fd51cf206), [f60bcdd6f4d2](https://github.com/dropseed/plain/commit/f60bcdd6f4d2))
- **New `SERVER_CONNECTIONS` setting** — controls the maximum number of concurrent connections per worker (default: 1000). Replaces implicit connection limits ([322fd51cf206](https://github.com/dropseed/plain/commit/322fd51cf206))
- **New `SERVER_H2_MAX_CONCURRENT_STREAMS` setting** — optionally limits the number of concurrent HTTP/2 streams per connection ([322fd51cf206](https://github.com/dropseed/plain/commit/322fd51cf206))
- **Asyncio debug mode in development** — when `DEBUG=True`, the server enables asyncio debug mode which logs warnings when a callback blocks the event loop for more than 100ms, helping catch blocking calls in async views ([3afdae32ef94](https://github.com/dropseed/plain/commit/3afdae32ef94))
- Added documentation for async view safety, server request lifecycle, and three-layer architecture ([3afdae32ef94](https://github.com/dropseed/plain/commit/3afdae32ef94), [ca82fb46ad7e](https://github.com/dropseed/plain/commit/ca82fb46ad7e))

### Upgrade instructions

- Replace `self.url_args` with `self.url_kwargs` in all views. If you used positional URL arguments with unnamed regex groups, convert them to named groups (`(?P<name>...)`).
- Replace any `reverse(name, arg1, arg2)` calls with `reverse(name, param1=arg1, param2=arg2)` using keyword arguments.
- Replace any `reverse_absolute(name, arg1)` calls similarly.
- In templates, replace `url("name", arg1)` with `url("name", param1=arg1)` using keyword arguments.
- No server configuration changes are required — the new settings have sensible defaults.

## [0.118.0](https://github.com/dropseed/plain/releases/plain@0.118.0) (2026-03-06)

### What's changed

- **Removed `as_view()` and `setup()` from View** — views are now passed as classes directly to URL patterns (e.g., `path("foo/", MyView)` instead of `path("foo/", MyView.as_view())`). The `setup()` method is removed; request, URL args, and URL kwargs are set directly on the view instance. `View.__init__` no longer accepts arguments. The `view_class` attribute moved from `URLPattern.view` to `URLPattern.view_class` directly ([0d0c8a64cb45](https://github.com/dropseed/plain/commit/0d0c8a64cb45))
- **Removed `--pidfile` option from server** — the `--pidfile` CLI option and `SERVER_PIDFILE` setting have been removed ([3ac519e691b2](https://github.com/dropseed/plain/commit/3ac519e691b2))
- **Removed `--max-requests` option from server** — the `--max-requests` CLI option and `SERVER_MAX_REQUESTS` setting have been removed ([b48cdbafad33](https://github.com/dropseed/plain/commit/b48cdbafad33))
- Unified server dispatch through `handler.handle()`, consolidating the request pipeline for both HTTP/1.1 and HTTP/2 ([e47efeb99332](https://github.com/dropseed/plain/commit/e47efeb99332))
- Fixed thread affinity in production request pipeline to ensure views run on the correct thread ([6827fe551702](https://github.com/dropseed/plain/commit/6827fe551702))

### Upgrade instructions

- Replace all `MyView.as_view()` calls in URL patterns with just `MyView`.
- Remove any `**kwargs` passed to `as_view()` — set attributes on the class or override methods instead.
- If you override `setup()` in a view, move that logic to `get()`, `post()`, or another view method.
- Remove any `--pidfile` or `--max-requests` flags from server invocations and the `SERVER_PIDFILE` / `SERVER_MAX_REQUESTS` settings.

## [0.117.1](https://github.com/dropseed/plain/releases/plain@0.117.1) (2026-03-06)

### What's changed

- Fixed 500 error handling to pass the actual exception to `ErrorView` instead of `None`, allowing error views to access exception details ([463177c8f0fa](https://github.com/dropseed/plain/commit/463177c8f0fa))

### Upgrade instructions

- No changes required.

## [0.117.0](https://github.com/dropseed/plain/releases/plain@0.117.0) (2026-03-06)

### What's changed

- **Async view dispatch** — views can now be `async`. The server detects async view methods and awaits them directly on the worker's asyncio event loop instead of dispatching to the thread pool, freeing thread pool slots for sync views ([b62c283ecd3d](https://github.com/dropseed/plain/commit/b62c283ecd3d))
- **`AsyncStreamingResponse`** — new response class that streams from an `async` generator without occupying a thread pool slot. Available as `from plain.http import AsyncStreamingResponse` ([b62c283ecd3d](https://github.com/dropseed/plain/commit/b62c283ecd3d))
- **`ServerSentEventsView`** — new view class for Server-Sent Events. Subclass it and implement an async `events()` generator that yields `SentEvent` objects. Handles SSE framing, `Cache-Control`, and `X-Accel-Buffering` headers automatically ([b62c283ecd3d](https://github.com/dropseed/plain/commit/b62c283ecd3d))

### Upgrade instructions

- No changes required.

## [0.116.0](https://github.com/dropseed/plain/releases/plain@0.116.0) (2026-03-06)

### What's changed

- **HTTP/2 support** — TLS connections now automatically negotiate HTTP/2 via ALPN. HTTP/2 requests are handled with full stream multiplexing using the `h2` library, while HTTP/1.1 clients continue to work as before. Each HTTP/2 stream is dispatched to the thread pool independently, and idle connections time out after 5 minutes ([c4d3a33671c6](https://github.com/dropseed/plain/commit/c4d3a33671c6))
- **Middleware refactored to before/after phases** — `HttpMiddleware` no longer uses the onion/wrapper model with `process_request()` and `self.get_response()`. Instead, middleware now implements `before_request(request) -> Response | None` (return a response to short-circuit, or `None` to continue) and `after_response(request, response) -> Response` (modify and return the response). The middleware pipeline runs `before_request` forward through the chain, then `after_response` in reverse. Middleware `__init__` no longer receives `get_response` ([9a1477ee8fa8](https://github.com/dropseed/plain/commit/9a1477ee8fa8))
- Updated server architecture diagram and README to document HTTP/2 and the new middleware model ([c4d3a33671c6](https://github.com/dropseed/plain/commit/c4d3a33671c6), [9a1477ee8fa8](https://github.com/dropseed/plain/commit/9a1477ee8fa8))

### Upgrade instructions

- Rename `process_request(self, request)` to `before_request(self, request)` in custom middleware. The method should return `None` to continue to the next middleware/view, or return a `Response` to short-circuit.
- Move any post-response logic (code after `self.get_response(request)`) into a new `after_response(self, request, response)` method that returns the response.
- Remove `self.get_response(request)` calls — the framework now handles calling the next middleware/view automatically.
- Update `__init__` signatures: middleware `__init__` no longer receives `get_response`. Change `def __init__(self, get_response)` to `def __init__(self)` and remove `super().__init__(get_response)`.

## [0.115.0](https://github.com/dropseed/plain/releases/plain@0.115.0) (2026-03-05)

### What's changed

- **Asyncio worker event loop** — replaced the hand-rolled `selectors` event loop and `PollableMethodQueue` pipe with Python's `asyncio` as the worker's main loop. Connection acceptance, keepalive timeouts, and backpressure are now managed with native asyncio primitives (`create_task`, `wait_for`, `Event`, `add_reader`) while all request handling still runs synchronously in the thread pool via `run_in_executor` ([bc3f998f3fda](https://github.com/dropseed/plain/commit/bc3f998f3fda))
- **Accept-loop crash detection** — if a listener socket hits an unexpected error (e.g. EMFILE), the worker now detects it and shuts down for the arbiter to restart, instead of silently losing that listener ([bc3f998f3fda](https://github.com/dropseed/plain/commit/bc3f998f3fda))
- **Cleaner graceful shutdown** — uses `asyncio.wait()` with timeout and task cancellation, and cancels accept loops before closing listener sockets to avoid EBADF errors ([bc3f998f3fda](https://github.com/dropseed/plain/commit/bc3f998f3fda))

### Upgrade instructions

- No changes required.

## [0.114.1](https://github.com/dropseed/plain/releases/plain@0.114.1) (2026-03-04)

### What's changed

- Fixed server error responses being malformed on Python 3.14 due to a `textwrap.dedent()` behavior change that strips `\r` as whitespace, breaking the `\r\n\r\n` header-body separator ([6e61cf5e39b3](https://github.com/dropseed/plain/commit/6e61cf5e39b3))

### Upgrade instructions

- No changes required.

## [0.114.0](https://github.com/dropseed/plain/releases/plain@0.114.0) (2026-03-04)

### What's changed

- **Lock-free thread worker event loop** — replaced `RLock` and `futures.wait()` with a pipe-based `PollableMethodQueue` that defers worker thread completions back to the main thread, eliminating all lock contention in the connection handling hot path ([d0ecd12bbe](https://github.com/dropseed/plain/commit/d0ecd12bbe))
- **Unified event loop** — the main loop now uses a single `poller.select()` call for accepts, client data, and worker completions instead of splitting between `poller.select()` and `futures.wait()` ([d0ecd12bbe](https://github.com/dropseed/plain/commit/d0ecd12bbe))
- **Backpressure on accept** — listener sockets are dynamically registered/unregistered from the poller when at connection capacity, preventing thread pool exhaustion under load ([d0ecd12bbe](https://github.com/dropseed/plain/commit/d0ecd12bbe))
- **Slow client timeout** — new connections now get a read timeout during request parsing so slow or stalled clients can't hold a thread pool slot indefinitely ([d0ecd12bbe](https://github.com/dropseed/plain/commit/d0ecd12bbe))
- **Graceful shutdown improvement** — shutdown now drains in-flight requests via the method queue instead of polling futures ([d0ecd12bbe](https://github.com/dropseed/plain/commit/d0ecd12bbe))
- Added `HTTPS_PROXY_HEADER` upgrade warning to 0.113.0 changelog ([b1d63fda04](https://github.com/dropseed/plain/commit/b1d63fda04))

### Upgrade instructions

- No changes required.

## [0.113.0](https://github.com/dropseed/plain/releases/plain@0.113.0) (2026-03-04)

### What's changed

- **Removed WSGI layer entirely** — the server now creates `Request` objects directly and writes `Response` to sockets, eliminating the WSGI environ abstraction ([163c31ba9f](https://github.com/dropseed/plain/commit/163c31ba9f), [4a4fe406086a](https://github.com/dropseed/plain/commit/4a4fe406086a))
- `Request.__init__` now accepts `method`, `path`, `headers`, and connection params directly instead of a WSGI environ dict ([f25f430f54b4](https://github.com/dropseed/plain/commit/f25f430f54b4), [1c9ab9e67611](https://github.com/dropseed/plain/commit/1c9ab9e67611))
- Test client creates `Request` directly without WSGI environ ([bed765f3ff77](https://github.com/dropseed/plain/commit/bed765f3ff77))
- Centralized header normalization in `RequestHeaders` class, simplifying `Request` attributes ([acec7dfd89be](https://github.com/dropseed/plain/commit/acec7dfd89be))
- Removed `LimitedStream` — body size limit is now enforced during reads ([cb8ac54654f3](https://github.com/dropseed/plain/commit/cb8ac54654f3))
- Simplified `Response` by removing WSGI-era `start_response` method ([7cea8c314449](https://github.com/dropseed/plain/commit/7cea8c314449))
- **Server migrated from fork to spawn** for process creation, with simplified process supervisor ([a19c13255a4d](https://github.com/dropseed/plain/commit/a19c13255a4d))
- Flattened `Worker` classes and moved runtime setup to worker entry point ([ce1114615d86](https://github.com/dropseed/plain/commit/ce1114615d86))
- Removed server-level scheme detection, unified on `HTTPS_PROXY_HEADER` setting ([05eea6446830](https://github.com/dropseed/plain/commit/05eea6446830))
- Added `Host` header validation per RFC 9112 §3.2 ([bd07db36aec2](https://github.com/dropseed/plain/commit/bd07db36aec2))
- **Structured access logging** — server access log now uses structured context logging with configurable fields ([72a905fbe1c3](https://github.com/dropseed/plain/commit/72a905fbe1c3))
- Removed standard log format — only `keyvalue` or `json` log formats are supported ([96ad632e6f28](https://github.com/dropseed/plain/commit/96ad632e6f28))
- Replaced `Logger` class with module-level functions and standard logging ([24d9665818de](https://github.com/dropseed/plain/commit/24d9665818de))
- Removed logging CLI options from server command ([d00dc098b32d](https://github.com/dropseed/plain/commit/d00dc098b32d))
- Added `SERVER_*` settings for server configuration ([9fadf8bafec2](https://github.com/dropseed/plain/commit/9fadf8bafec2))
- Added per-response access log control and `ASSETS_LOG_304` setting to suppress noisy asset 304s ([4250db0ed02e](https://github.com/dropseed/plain/commit/4250db0ed02e))
- Changed `--access-log` from file path to boolean flag ([6924211917f6](https://github.com/dropseed/plain/commit/6924211917f6))
- Preflight badge rendered inline in HTML instead of JavaScript fetch ([2894abfc5d98](https://github.com/dropseed/plain/commit/2894abfc5d98))
- Removed dead signal handlers (SIGUSR1, SIGUSR2, SIGWINCH, SIGHUP, SIGTTIN, SIGTTOU) ([37f13c730b47](https://github.com/dropseed/plain/commit/37f13c730b47))
- Deleted `Config` dataclass — server params are passed directly ([4989df5eb147](https://github.com/dropseed/plain/commit/4989df5eb147))
- Removed dead file-logging code from server ([7f4f80fa0ff4](https://github.com/dropseed/plain/commit/7f4f80fa0ff4))

### Upgrade instructions

- **WSGI removed** — The WSGI layer (`plain.wsgi`) has been completely removed. You can no longer use third-party WSGI servers (gunicorn, uvicorn, etc.) — use `plain server` directly. If you had a `wsgi.py` entry point, remove it.
- **`Request()` constructor changed** — `Request()` now requires `method` and `path` keyword arguments. Code that constructed `Request` objects directly (e.g., in tests) must be updated: `Request(method="GET", path="/")`.
- **`request_started` signal changed** — The signal no longer sends an `environ` keyword argument. If you connected to `request_started`, update your receiver to not expect `environ`.
- **`WEB_CONCURRENCY` → `SERVER_WORKERS`** — The `--workers` CLI option now reads from the `SERVER_WORKERS` setting (default: `0` for auto/CPU count). `WEB_CONCURRENCY` env var is still read as a fallback in the default setting, but the canonical way is now `PLAIN_SERVER_WORKERS` env var or `SERVER_WORKERS` in settings.
- **New `SERVER_*` settings** — Server configuration has moved from CLI-only options to settings: `SERVER_WORKERS`, `SERVER_THREADS`, `SERVER_TIMEOUT`, `SERVER_MAX_REQUESTS`, `SERVER_ACCESS_LOG`, `SERVER_ACCESS_LOG_FIELDS`, `SERVER_GRACEFUL_TIMEOUT`, `SERVER_SENDFILE`. CLI flags still work as overrides.
- **Log format `standard` removed** — Only `keyvalue` or `json` are supported. Update `LOG_FORMAT` if you were using `standard`.
- **Server logging CLI options removed** — `--log-level`, `--log-format`, and `--access-log-format` have been removed. Configure via settings or environment variables instead.
- **`--access-log` is now a boolean** — Use `--access-log` / `--no-access-log` instead of passing a file path. Access logs always go to stdout.
- **`HTTPS_PROXY_HEADER` now required behind reverse proxies** — The server no longer auto-detects HTTPS from the connection. If your app runs behind an SSL-terminating proxy (Heroku, AWS ALB, nginx, etc.) and `HTTPS_REDIRECT_ENABLED` is `True` (the default), you **must** set `HTTPS_PROXY_HEADER` or you'll get an infinite 301 redirect loop. For example, on Heroku: `HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"` (or set `PLAIN_HTTPS_PROXY_HEADER="X-Forwarded-Proto: https"` as an env var).
- **Server process model changed from fork to spawn** — This should be transparent, but if you relied on fork-inherited state in worker processes, it will no longer be available.
- **`LimitedStream` removed** — Body size limits are now enforced automatically during reads.
- **`HEADER_MAP` config removed** — Underscore-containing headers are always dropped (the previous default behavior). The `refuse` and `dangerous` options no longer exist.

## [0.112.1](https://github.com/dropseed/plain/releases/plain@0.112.1) (2026-03-03)

### What's changed

- `settings.get_settings()` now skips internal settings whose names start with `_` ([7bd0064bdc](https://github.com/dropseed/plain/commit/7bd0064bdc))

### Upgrade instructions

- No changes required.

## [0.112.0](https://github.com/dropseed/plain/releases/plain@0.112.0) (2026-02-28)

### What's changed

- Removed `DEFAULT_CHARSET` setting — the charset is now always `utf-8`, which was already the default. All references in `QueryDict`, `ResponseBase`, multipart parsing, and test utilities now use the hardcoded value directly ([901e6b3c49](https://github.com/dropseed/plain/commit/901e6b3c49))

### Upgrade instructions

- If you were customizing `DEFAULT_CHARSET` in your settings, remove it. UTF-8 is now always used.

## [0.111.0](https://github.com/dropseed/plain/releases/plain@0.111.0) (2026-02-26)

### What's changed

- Added built-in `HEALTHCHECK_PATH` setting — when set, requests to this exact path return a `200` response before any middleware runs, avoiding ALLOWED_HOSTS rejection and HTTPS redirect loops from health checkers ([2c25ccbadd](https://github.com/dropseed/plain/commit/2c25ccbadd))
- Fixed test client to handle responses from middleware that bypass URL routing (e.g. healthcheck) — previously missing sessions or unresolvable paths would raise exceptions ([bcd8913f02](https://github.com/dropseed/plain/commit/bcd8913f02))
- Custom settings (prefixed with `APP_`) now resolve type annotations properly, enabling environment variable parsing for custom settings ([d9fff3223e](https://github.com/dropseed/plain/commit/d9fff3223e))
- Secret settings now show collection size hints (e.g. `{******** (3 items)}`) instead of a flat `********` for dict, list, and tuple values ([d9fff3223e](https://github.com/dropseed/plain/commit/d9fff3223e))
- `plain docs --search` now supports `--api` to also search public API symbols ([e3ef3f3d84](https://github.com/dropseed/plain/commit/e3ef3f3d84))
- `plain docs --section` now matches `###` subsections in addition to `##` sections ([9db0491a3f](https://github.com/dropseed/plain/commit/9db0491a3f))

### Upgrade instructions

- No changes required.

## [0.110.1](https://github.com/dropseed/plain/releases/plain@0.110.1) (2026-02-26)

### What's changed

- Added type annotations to all settings in `global_settings.py` so they can be set via environment variables — previously 11 settings like `HTTPS_REDIRECT_ENABLED`, `APPEND_SLASH`, and `FILE_UPLOAD_MAX_MEMORY_SIZE` were missing annotations and would error when set via env vars ([37e8a58ca9b5](https://github.com/dropseed/plain/commit/37e8a58ca9b5))

### Upgrade instructions

- No changes required.

## [0.110.0](https://github.com/dropseed/plain/releases/plain@0.110.0) (2026-02-26)

### What's changed

- Environment variables now take highest precedence, overriding values set in `settings.py` — previously explicit settings would win over env vars ([0d40bcfcd539](https://github.com/dropseed/plain/commit/0d40bcfcd539))
- Moved SSL handshake from the main thread to the worker thread so handshake errors no longer crash the main loop, ported from gunicorn PR #3440 ([6309ef82642e](https://github.com/dropseed/plain/commit/6309ef82642e))
- Switched keepalive timeouts to use `time.monotonic()` instead of `time.time()` for correctness during clock adjustments ([e7ddd1a31cfe](https://github.com/dropseed/plain/commit/e7ddd1a31cfe))
- Extracted `finish_body()` method on the HTTP parser for explicit cleanup before returning keepalive connections to the poller ([0cf51dd17c6f](https://github.com/dropseed/plain/commit/0cf51dd17c6f))

### Upgrade instructions

- If you rely on `settings.py` values taking precedence over `PLAIN_`-prefixed environment variables, be aware that env vars now win. Remove any env vars that conflict with values you want to set in code.

## [0.109.0](https://github.com/dropseed/plain/releases/plain@0.109.0) (2026-02-26)

### What's changed

- Added `--outline` flag to `plain docs` CLI to display section headings for quick navigation ([153502ee90f5](https://github.com/dropseed/plain/commit/153502ee90f5))
- Added `--search` flag to `plain docs` CLI to find which modules and sections mention a term ([153502ee90f5](https://github.com/dropseed/plain/commit/153502ee90f5))
- Enhanced `plain docs --list` to show core modules alongside packages, with color-coded output ([3f34b5405ea3](https://github.com/dropseed/plain/commit/3f34b5405ea3))
- Updated shell banner to show app name and version in a styled box instead of generic welcome message ([a7b152d0baf8](https://github.com/dropseed/plain/commit/a7b152d0baf8))

### Upgrade instructions

- No changes required.

## [0.108.1](https://github.com/dropseed/plain/releases/plain@0.108.1) (2026-02-26)

### What's changed

- Fixed `plain request` to use `localhost` as SERVER_NAME and default the Accept header to `text/html`, matching typical browser behavior ([01731c5485cf](https://github.com/dropseed/plain/commit/01731c5485cf))
- Updated `plain-bug` skill to create GitHub Issues via `gh` CLI instead of posting to the Plain API ([ce7b95bd056d](https://github.com/dropseed/plain/commit/ce7b95bd056d))

### Upgrade instructions

- No changes required.

## [0.108.0](https://github.com/dropseed/plain/releases/plain@0.108.0) (2026-02-24)

### What's changed

- Added absolute URL generation: new `absolute_url()` and `reverse_absolute()` functions that prepend the scheme and domain using a new `BASE_URL` setting ([1e0d09f3ec70](https://github.com/dropseed/plain/commit/1e0d09f3ec70))
- Added `reverse_absolute` and `absolute_url` as Jinja template globals for use in templates ([1e0d09f3ec70](https://github.com/dropseed/plain/commit/1e0d09f3ec70))
- Added `reverse` as an explicit template global (previously only available as `url`) ([1e0d09f3ec70](https://github.com/dropseed/plain/commit/1e0d09f3ec70))

### Upgrade instructions

- No changes required. To use absolute URLs, set `BASE_URL` in your settings (e.g. `BASE_URL = "https://example.com"`).

## [0.107.0](https://github.com/dropseed/plain/releases/plain@0.107.0) (2026-02-24)

### What's changed

- Added `SettingOption` — a custom Click option class that reads defaults from Plain settings, bridging CLI options to the settings system ([cb5353b9d266](https://github.com/dropseed/plain/commit/cb5353b9d266))
- Removed `SyncWorker` from the built-in HTTP server; `ThreadWorker` is now the only worker type ([c38ee93de5b4](https://github.com/dropseed/plain/commit/c38ee93de5b4))
- Changed `plain server` defaults to `--workers auto` (one per CPU core) and `--threads 4` for better out-of-the-box concurrency ([c38ee93de5b4](https://github.com/dropseed/plain/commit/c38ee93de5b4))

### Upgrade instructions

- If you relied on `SyncWorker` or single-threaded behavior, explicitly pass `--threads 1` to `plain server`.
- If you pinned `--workers 1`, note the default is now `auto`. Pass `--workers 1` explicitly to keep the old behavior.

## [0.106.2](https://github.com/dropseed/plain/releases/plain@0.106.2) (2026-02-13)

### What's changed

- Added `--version` flag to the `plain` CLI to display the installed version ([e76fd7070302](https://github.com/dropseed/plain/commit/e76fd7070302))

### Upgrade instructions

- No changes required.

## [0.106.1](https://github.com/dropseed/plain/releases/plain@0.106.1) (2026-02-13)

### What's changed

- Added `--section` flag to `plain docs` for loading a specific `##` section by name (e.g., `plain docs models --section querying`) ([f2ce0243e6ea](https://github.com/dropseed/plain/commit/f2ce0243e6ea))
- Simplified `plain docs` output by removing XML-style wrapper tags around documentation content ([f2ce0243e6ea](https://github.com/dropseed/plain/commit/f2ce0243e6ea))
- Added `/plain-bug` skill for submitting bug reports to plainframework.com ([a9efc4383233](https://github.com/dropseed/plain/commit/a9efc4383233))
- Slimmed agent rules to concise bullet-point reminders and moved detailed code examples into README docs ([f5d2731ebda0](https://github.com/dropseed/plain/commit/f5d2731ebda0))
- Added Forms section to templates README and View patterns section to views README ([8c2189a896d2](https://github.com/dropseed/plain/commit/8c2189a896d2))
- Fixed agents exclusion in LLM docs to only exclude `.claude/` content, allowing `agents/README.md` to appear in docs output ([f2ce0243e6ea](https://github.com/dropseed/plain/commit/f2ce0243e6ea))

### Upgrade instructions

- No changes required.

## [0.106.0](https://github.com/dropseed/plain/releases/plain@0.106.0) (2026-02-12)

### What's changed

- Added `plain check` command that runs core validation checks in sequence: custom commands, code linting, preflight, migration state, and tests ([430268a12ae2](https://github.com/dropseed/plain/commit/430268a12ae2))
- Added assertion flags to `plain request`: `--status`, `--contains`, and `--not-contains` for automated response testing ([6b66bfd05b9e](https://github.com/dropseed/plain/commit/6b66bfd05b9e))
- Fixed `plain request` crash when no user model exists ([8ef8a3813bff](https://github.com/dropseed/plain/commit/8ef8a3813bff))
- `plain request` now exits non-zero on server errors (5xx) and all failure paths ([6b66bfd05b9e](https://github.com/dropseed/plain/commit/6b66bfd05b9e))
- Updated agent rules with additional Django-to-Plain differences (model options, CSRF, forms, middleware) ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))

### Upgrade instructions

- No changes required.

## [0.105.0](https://github.com/dropseed/plain/releases/plain@0.105.0) (2026-02-05)

### What's changed

- `plain agent install` now discovers and installs rules and skills from `plainx.*` namespace packages in addition to `plain.*` packages ([bd568db924f7](https://github.com/dropseed/plain/commit/bd568db924f7))
- Orphan cleanup during `plain agent install` now correctly handles both `plain` and `plainx` prefixed items ([bd568db924f7](https://github.com/dropseed/plain/commit/bd568db924f7))

### Upgrade instructions

- No changes required.

## [0.104.1](https://github.com/dropseed/plain/releases/plain@0.104.1) (2026-02-04)

### What's changed

- Added `__all__` exports to public modules for improved IDE autocompletion and explicit public API boundaries ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2), [f26a63a5c941](https://github.com/dropseed/plain/commit/f26a63a5c941))
- Removed `@internalcode` decorator from internal classes in favor of `__all__` exports ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Renamed `plain docs --symbols` option to `--api` for clarity ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- If using `plain docs --symbols`, update to `plain docs --api`.

## [0.104.0](https://github.com/dropseed/plain/releases/plain@0.104.0) (2026-02-04)

### What's changed

- Refactored the assets manifest system with a clearer API: `AssetsManifest` replaces `AssetsFingerprintsManifest`, with explicit methods `add_fingerprinted()`, `add_non_fingerprinted()`, `is_fingerprinted()`, and `resolve()` ([9cb84010b5fb](https://github.com/dropseed/plain/commit/9cb84010b5fb))
- Renamed `ASSETS_BASE_URL` setting to `ASSETS_CDN_URL` for clarity ([9cb84010b5fb](https://github.com/dropseed/plain/commit/9cb84010b5fb))
- When `ASSETS_CDN_URL` is configured, `AssetsRouter` now redirects compiled assets to the CDN: original paths use 302 (temporary), fingerprinted paths use 301 (permanent) with immutable caching ([9cb84010b5fb](https://github.com/dropseed/plain/commit/9cb84010b5fb))
- The `is_immutable()` check now uses the manifest to determine if a path is fingerprinted, rather than pattern-matching the filename ([9cb84010b5fb](https://github.com/dropseed/plain/commit/9cb84010b5fb))

### Upgrade instructions

- Rename `ASSETS_BASE_URL` to `ASSETS_CDN_URL` in your settings if you use a CDN for assets.
- If you were importing from `plain.assets.fingerprints`, update imports to use `plain.assets.manifest` instead:
    - `AssetsFingerprintsManifest` → `AssetsManifest`
    - `get_fingerprinted_url_path()` → `get_manifest().resolve()`
    - `_get_file_fingerprint()` → `compute_fingerprint()`

## [0.103.2](https://github.com/dropseed/plain/releases/plain@0.103.2) (2026-02-02)

### What's changed

- Compiled assets now use deterministic gzip output by setting `mtime=0`, ensuring consistent file hashes across builds ([dc76e03879fc](https://github.com/dropseed/plain/commit/dc76e03879fc))
- Agent rules now include a "Key Differences from Django" section to help Claude avoid common mistakes when working with Plain ([02e11328dbf5](https://github.com/dropseed/plain/commit/02e11328dbf5))

### Upgrade instructions

- No changes required.

## [0.103.1](https://github.com/dropseed/plain/releases/plain@0.103.1) (2026-01-30)

### What's changed

- `load_dotenv()` now sets each environment variable immediately as it is parsed, so command substitutions like `$(echo $TOKEN)` can reference variables defined earlier in the same `.env` file ([cecb71a016](https://github.com/dropseed/plain/commit/cecb71a016))

### Upgrade instructions

- No changes required.

## [0.103.0](https://github.com/dropseed/plain/releases/plain@0.103.0) (2026-01-30)

### What's changed

- `plain docs` now shows markdown documentation by default (previously required `--source`), with a new `--symbols` flag to show only the symbolicated API surface ([b71dab9d5d](https://github.com/dropseed/plain/commit/b71dab9d5d))
- `plain docs --list` now shows all official Plain packages (installed and uninstalled) with descriptions and install status ([9cba705d62](https://github.com/dropseed/plain/commit/9cba705d62))
- `plain docs` for uninstalled packages now shows the install command and an online docs URL instead of a generic error ([9cba705d62](https://github.com/dropseed/plain/commit/9cba705d62))
- Removed the `plain agent context` command and the `SessionStart` hook setup — agent rules now provide context directly without needing a startup hook ([88d9424643](https://github.com/dropseed/plain/commit/88d9424643))
- `plain agent install` now cleans up old SessionStart hooks from `.claude/settings.json` ([88d9424643](https://github.com/dropseed/plain/commit/88d9424643))

### Upgrade instructions

- The `--source` flag for `plain docs` has been removed. Use `--symbols` instead to see the symbolicated API surface.
- The `--open` flag for `plain docs` has been removed.
- Run `plain agent install` to clean up the old SessionStart hook from your `.claude/settings.json`.

## [0.102.0](https://github.com/dropseed/plain/releases/plain@0.102.0) (2026-01-28)

### What's changed

- Refactored agent integration from skills-based to rules-based: packages now provide `agents/.claude/rules/` files and `agents/.claude/skills/` directories instead of `skills/` directories ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))
- The `plain agent install` command now copies both rules (`.md` files) and skills to the project's `.claude/` directory, and cleans up orphaned `plain*` items ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))
- Removed standalone skills (`plain-docs`, `plain-shell`, `plain-request`) that are now provided as passive rules instead ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory with the new rules-based structure.

## [0.101.2](https://github.com/dropseed/plain/releases/plain@0.101.2) (2026-01-28)

### What's changed

- When `load_dotenv()` is called with `override=False` (the default), command substitution is now skipped for keys that already exist in `os.environ`. This prevents redundant command execution in child processes that re-load the `.env` file after inheriting resolved values from the parent, avoiding multiple auth prompts with tools like the 1Password CLI ([2f6ff93499](https://github.com/dropseed/plain/commit/2f6ff93499))
- The `_execute_command` helper now uses `stdout=subprocess.PIPE` instead of `capture_output=True`, allowing stderr/tty to pass through for interactive prompts ([2f6ff93499](https://github.com/dropseed/plain/commit/2f6ff93499))
- Updated templates README examples to use `id` instead of `pk` ([837d345d23](https://github.com/dropseed/plain/commit/837d345d23))
- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.101.1](https://github.com/dropseed/plain/releases/plain@0.101.1) (2026-01-17)

### What's changed

- Fixed a crash when running the development server with `--reload` when an app's `assets` directory doesn't exist ([df33f93ece](https://github.com/dropseed/plain/commit/df33f93ece))
- The `plain agent install` command now preserves user-created skills (those without the `plain-` prefix) instead of removing them as orphans ([bbc87498ed](https://github.com/dropseed/plain/commit/bbc87498ed))

### Upgrade instructions

- No changes required.

## [0.101.0](https://github.com/dropseed/plain/releases/plain@0.101.0) (2026-01-15)

### What's changed

- The `plain server` command now accepts `--workers auto` (or `WEB_CONCURRENCY=auto`) to automatically set worker count based on CPU count ([02a1769948](https://github.com/dropseed/plain/commit/02a1769948))
- Response headers can now be set to `None` to opt out of default headers; `None` values are filtered out at the WSGI layer rather than being deleted by middleware ([cbf27e728d](https://github.com/dropseed/plain/commit/cbf27e728d))
- Removed unused `Response` methods: `serialize_headers`, `serialize`, file-like interface stubs (`write`, `flush`, `tell`, `readable`, `seekable`, `writable`, `writelines`), `text` property, pickling support, and `getvalue` ([cbf27e728d](https://github.com/dropseed/plain/commit/cbf27e728d))

### Upgrade instructions

- No changes required

## [0.100.1](https://github.com/dropseed/plain/releases/plain@0.100.1) (2026-01-15)

### What's changed

- The `plain agent install` command now only sets up session hooks for Claude Code, not Codex, since the `settings.json` hook format is Claude Code-specific ([a41e08bcd2](https://github.com/dropseed/plain/commit/a41e08bcd2))

### Upgrade instructions

- No changes required

## [0.100.0](https://github.com/dropseed/plain/releases/plain@0.100.0) (2026-01-15)

### What's changed

- The `plain skills` command has been renamed to `plain agent` with new subcommands: `plain agent install` (installs skills and sets up hooks), `plain agent skills` (lists available skills), and `plain agent context` (outputs framework context) ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- Added `SessionStart` hook that automatically runs `plain agent context` at the start of every Claude Code or Codex session, providing framework context without needing a separate skill ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- The `plain-principles` skill has been removed - its content is now provided by the `plain agent context` command via the SessionStart hook ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))
- Added `--no-headers` and `--no-body` flags to `plain request` for limiting output ([fac8673436](https://github.com/dropseed/plain/commit/fac8673436))

### Upgrade instructions

- Replace `plain skills --install` with `plain agent install`
- Replace `plain skills` (without flags) with `plain agent skills`
- Run `plain agent install` to set up the new SessionStart hook in your project's `.claude/` or `.codex/` directory

## [0.99.0](https://github.com/dropseed/plain/releases/plain@0.99.0) (2026-01-15)

### What's changed

- Added `plain.utils.dotenv` module with `load_dotenv()` and `parse_dotenv()` functions for bash-compatible `.env` file parsing, supporting variable expansion, command substitution, multiline values, and escape sequences ([a9b2dc3e16](https://github.com/dropseed/plain/commit/a9b2dc3e16))

### Upgrade instructions

- No changes required

## [0.98.1](https://github.com/dropseed/plain/releases/plain@0.98.1) (2026-01-13)

### What's changed

- Fixed `INSTALLED_PACKAGES` not being optional in user settings, restoring the default empty list behavior ([820773c473](https://github.com/dropseed/plain/commit/820773c473))

### Upgrade instructions

- No changes required

## [0.98.0](https://github.com/dropseed/plain/releases/plain@0.98.0) (2026-01-13)

### What's changed

- The `plain skills --install` command now removes orphaned skills from destination directories when skills are renamed or removed from packages ([d51294ace1](https://github.com/dropseed/plain/commit/d51294ace1))
- Added README documentation for `plain.skills` with available skills and installation instructions ([7c90fc8595](https://github.com/dropseed/plain/commit/7c90fc8595))

### Upgrade instructions

- No changes required

## [0.97.0](https://github.com/dropseed/plain/releases/plain@0.97.0) (2026-01-13)

### What's changed

- HTTP exceptions (`NotFoundError404`, `ForbiddenError403`, `BadRequestError400`, and `SuspiciousOperationError400` variants) moved from `plain.exceptions` to `plain.http.exceptions` and are now exported from `plain.http` ([b61f909e29](https://github.com/dropseed/plain/commit/b61f909e29))

### Upgrade instructions

- Update imports of HTTP exceptions from `plain.exceptions` to `plain.http`:

    ```python
    # Before
    from plain.exceptions import NotFoundError404, ForbiddenError403, BadRequestError400

    # After
    from plain.http import NotFoundError404, ForbiddenError403, BadRequestError400
    ```

## [0.96.0](https://github.com/dropseed/plain/releases/plain@0.96.0) (2026-01-13)

### What's changed

- Response classes renamed for consistency: `ResponseRedirect` → `RedirectResponse`, `ResponseNotModified` → `NotModifiedResponse`, `ResponseNotAllowed` → `NotAllowedResponse` ([fad5bf28b0](https://github.com/dropseed/plain/commit/fad5bf28b0))
- Redundant response classes removed: `ResponseNotFound`, `ResponseForbidden`, `ResponseBadRequest`, `ResponseGone`, `ResponseServerError` - use `Response(status_code=X)` instead ([fad5bf28b0](https://github.com/dropseed/plain/commit/fad5bf28b0))
- HTTP exceptions renamed to include status code suffix: `Http404` → `NotFoundError404`, `PermissionDenied` → `ForbiddenError403`, `BadRequest` → `BadRequestError400`, `SuspiciousOperation` → `SuspiciousOperationError400` ([5a1f020f52](https://github.com/dropseed/plain/commit/5a1f020f52))
- Added `Secret[T]` type annotation for masking sensitive settings like `SECRET_KEY` in CLI output ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Added `ENV_SETTINGS_PREFIXES` setting to configure which environment variable prefixes are checked for settings (defaults to `["PLAIN_"]`) ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- New `plain settings list` and `plain settings get` CLI commands for viewing settings with their sources ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Added preflight check for unused environment variables matching configured prefixes ([8713dc08b0](https://github.com/dropseed/plain/commit/8713dc08b0))
- Renamed `request.meta` to `request.environ` for clarity ([786b95bef8](https://github.com/dropseed/plain/commit/786b95bef8))
- Added `request.query_string` and `request.content_length` properties ([786b95bef8](https://github.com/dropseed/plain/commit/786b95bef8), [76dfd477d2](https://github.com/dropseed/plain/commit/76dfd477d2))
- Renamed X-Forwarded settings: `USE_X_FORWARDED_HOST` → `HTTP_X_FORWARDED_HOST`, `USE_X_FORWARDED_PORT` → `HTTP_X_FORWARDED_PORT`, `USE_X_FORWARDED_FOR` → `HTTP_X_FORWARDED_FOR` ([22f241a55c](https://github.com/dropseed/plain/commit/22f241a55c))
- Changed `HTTPS_PROXY_HEADER` from a tuple to a string format (e.g., `"X-Forwarded-Proto: https"`) ([7ac2a431b6](https://github.com/dropseed/plain/commit/7ac2a431b6))

### Upgrade instructions

- Replace Response class imports and usages:
    - `ResponseRedirect` → `RedirectResponse`
    - `ResponseNotModified` → `NotModifiedResponse`
    - `ResponseNotAllowed` → `NotAllowedResponse`
    - `ResponseNotFound` → `Response(status_code=404)`
    - `ResponseForbidden` → `Response(status_code=403)`
    - `ResponseBadRequest` → `Response(status_code=400)`
    - `ResponseGone` → `Response(status_code=410)`
    - `ResponseServerError` → `Response(status_code=500)`
- Replace exception imports and usages:
    - `Http404` → `NotFoundError404`
    - `PermissionDenied` → `ForbiddenError403`
    - `BadRequest` → `BadRequestError400`
    - `SuspiciousOperation` → `SuspiciousOperationError400`
    - `SuspiciousMultipartForm` → `SuspiciousMultipartFormError400`
    - `SuspiciousFileOperation` → `SuspiciousFileOperationError400`
    - `TooManyFieldsSent` → `TooManyFieldsSentError400`
    - `TooManyFilesSent` → `TooManyFilesSentError400`
    - `RequestDataTooBig` → `RequestDataTooBigError400`
- Replace `request.meta` with `request.environ`
- Rename X-Forwarded settings in your configuration:
    - `USE_X_FORWARDED_HOST` → `HTTP_X_FORWARDED_HOST`
    - `USE_X_FORWARDED_PORT` → `HTTP_X_FORWARDED_PORT`
    - `USE_X_FORWARDED_FOR` → `HTTP_X_FORWARDED_FOR`
- Update `HTTPS_PROXY_HEADER` from tuple format to string format:

    ```python
    # Before
    HTTPS_PROXY_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # After
    HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"
    ```

- Replace `plain setting <name>` command with `plain settings get <name>`

## [0.95.0](https://github.com/dropseed/plain/releases/plain@0.95.0) (2025-12-22)

### What's changed

- Improved thread worker server shutdown behavior with `cancel_futures=True` for faster and cleaner process termination ([72d0620](https://github.com/dropseed/plain/commit/72d0620094))

### Upgrade instructions

- No changes required

## [0.94.0](https://github.com/dropseed/plain/releases/plain@0.94.0) (2025-12-12)

### What's changed

- `FormFieldMissingError` exceptions are now automatically converted to HTTP 400 Bad Request responses with a warning log instead of causing a 500 error ([b38f6e5](https://github.com/dropseed/plain/commit/b38f6e50db))

### Upgrade instructions

- No changes required

## [0.93.1](https://github.com/dropseed/plain/releases/plain@0.93.1) (2025-12-09)

### What's changed

- Added type annotation for `request.unique_id` attribute to improve IDE support and type checking ([23af501](https://github.com/dropseed/plain/commit/23af501d09))

### Upgrade instructions

- No changes required

## [0.93.0](https://github.com/dropseed/plain/releases/plain@0.93.0) (2025-12-04)

### What's changed

- Improved type annotations across forms, HTTP handling, logging, and other core modules for better IDE support and type checking ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))
- Internal refactor of `TimestampSigner` to use composition instead of inheritance from `Signer`, maintaining the same public API ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.92.0](https://github.com/dropseed/plain/releases/plain@0.92.0) (2025-12-01)

### What's changed

- Added `request.client_ip` property to get the client's IP address, with support for `X-Forwarded-For` header when behind a trusted proxy ([cb0bc5d](https://github.com/dropseed/plain/commit/cb0bc5d08f))
- Added `USE_X_FORWARDED_FOR` setting to enable reading client IP from `X-Forwarded-For` header ([cb0bc5d](https://github.com/dropseed/plain/commit/cb0bc5d08f))
- Improved `print_event` CLI output styling with dimmed text for less visual noise ([b09edfd](https://github.com/dropseed/plain/commit/b09edfd2a1))

### Upgrade instructions

- No changes required

## [0.91.0](https://github.com/dropseed/plain/releases/plain@0.91.0) (2025-11-24)

### What's changed

- Request body parsing refactored: the `request.data` attribute has been replaced with `request.json_data` and `request.form_data` for explicit content-type handling ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- `QueryDict` now has proper type annotations for `get()`, `pop()`, `getlist()`, and `__getitem__()` methods that reflect string return types ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- Forms now automatically select between `json_data` and `form_data` based on request content-type ([90332a9](https://github.com/dropseed/plain/commit/90332a9c21))
- View mixins `ObjectTemplateViewMixin` removed in favor of class inheritance for better typing - `UpdateView` and `DeleteView` now inherit from `DetailView` ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))
- `AppLogger` context logging now uses a `context` dict parameter instead of `**kwargs` for better type checking ([581b406](https://github.com/dropseed/plain/commit/581b4060d3))
- Removed erroneous `AuthViewMixin` export from `plain.views` ([334bbb6](https://github.com/dropseed/plain/commit/334bbb6e7a))

### Upgrade instructions

- Replace `request.data` with the appropriate method:
    - For JSON requests: use `request.json_data` (returns a dict, raises `BadRequest` for invalid JSON)
    - For form data: use `request.form_data` (returns a `QueryDict`)
- Update `app_logger` calls that pass context as kwargs to use the `context` parameter:

    ```python
    # Before
    app_logger.info("Message", user_id=123, action="login")

    # After
    app_logger.info("Message", context={"user_id": 123, "action": "login"})
    ```

## [0.90.0](https://github.com/dropseed/plain/releases/plain@0.90.0) (2025-11-20)

### What's changed

- Improved type annotations in `timezone.py`: `is_aware()` and `is_naive()` now accept both `datetime` and `time` objects for more flexible type checking ([a43145e](https://github.com/dropseed/plain/commit/a43145e697))
- Enhanced type annotations in view classes: `convert_value_to_response()` and handler result variables now use more explicit type hints for better IDE support ([dc4454e](https://github.com/dropseed/plain/commit/dc4454e196))
- Fixed type errors in forms and server workers: URL field now handles bytes properly, and worker wait_fds has explicit type annotation ([fc98d66](https://github.com/dropseed/plain/commit/fc98d666d4))

### Upgrade instructions

- No changes required

## [0.89.0](https://github.com/dropseed/plain/releases/plain@0.89.0) (2025-11-14)

### What's changed

- Improved type annotations in view classes: `url_args`, `url_kwargs`, and various template/form context dictionaries now have more specific type hints for better IDE support and type checking ([83bcb95](https://github.com/dropseed/plain/commit/83bcb95b09))

### Upgrade instructions

- No changes required

## [0.88.0](https://github.com/dropseed/plain/releases/plain@0.88.0) (2025-11-13)

### What's changed

- The `plain.forms` module now uses explicit imports instead of wildcard imports, improving IDE autocomplete and type checking support ([eff36f3](https://github.com/dropseed/plain/commit/eff36f31e8e15f84e11164a44c833aeab096ffbd))

### Upgrade instructions

- No changes required

## [0.87.0](https://github.com/dropseed/plain/releases/plain@0.87.0) (2025-11-12)

### What's changed

- Internal classes now use abstract base classes with `@abstractmethod` decorators instead of raising `NotImplementedError`, improving type checking and IDE support ([91b329a](https://github.com/dropseed/plain/commit/91b329a8adb477031c4358e638b12f35f19bb85d), [81b5f88](https://github.com/dropseed/plain/commit/81b5f88a4bd39785f6b19c3c00c0ed23a36fb72f), [d2e2423](https://github.com/dropseed/plain/commit/d2e24235f497a92f45d5a21fc83d802897c2dec0), [61e7b5a](https://github.com/dropseed/plain/commit/61e7b5a0c8675aaaf65f0a626ff7959a786dca7f))
- Updated to latest version of `ty` type checker and fixed type errors and warnings throughout the codebase ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa929058be517cb1d4ab35bd73a89f26b8))

### Upgrade instructions

- No changes required

## [0.86.2](https://github.com/dropseed/plain/releases/plain@0.86.2) (2025-11-11)

### What's changed

- CLI color output is now enabled in CI environments by checking the `CI` environment variable, matching the behavior of modern tools like uv ([a1500f15ed](https://github.com/dropseed/plain/commit/a1500f15ed))

### Upgrade instructions

- No changes required

## [0.86.1](https://github.com/dropseed/plain/releases/plain@0.86.1) (2025-11-10)

### What's changed

- The `plain preflight` command now outputs to stderr only when using `--format json`, keeping stdout clean for JSON parsing while avoiding success messages appearing in error logs for text format ([72ebee7729](https://github.com/dropseed/plain/commit/72ebee7729))
- CLI color handling now follows the CLICOLOR standard with proper priority: `NO_COLOR` > `CLICOLOR_FORCE`/`FORCE_COLOR` > `CLICOLOR` > `isatty` ([c7fea406c5](https://github.com/dropseed/plain/commit/c7fea406c5))

### Upgrade instructions

- No changes required

## [0.86.0](https://github.com/dropseed/plain/releases/plain@0.86.0) (2025-11-10)

### What's changed

- Log output is now split by severity level: INFO and below go to stdout, WARNING and above go to stderr for proper cloud platform log classification ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))
- Added `LOG_STREAM` setting to customize log output behavior with options: `"split"` (default), `"stdout"`, or `"stderr"` ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))
- Log configuration documentation expanded with detailed guidance on output streams and environment variable settings ([52403b15ba](https://github.com/dropseed/plain/commit/52403b15ba))

### Upgrade instructions

- No changes required (default behavior splits logs to stdout/stderr automatically, but this can be customized via `PLAIN_LOG_STREAM` environment variable if needed)

## [0.85.0](https://github.com/dropseed/plain/releases/plain@0.85.0) (2025-11-03)

### What's changed

- CLI help output now organizes commands into "Common Commands", "Core Commands", and "Package Commands" sections for better discoverability ([73d3a48](https://github.com/dropseed/plain/commit/73d3a48fca))
- CLI help output has been customized with improved formatting and shortcut indicators showing which commands are shortcuts (e.g., `migrate → models migrate`) ([db882e6](https://github.com/dropseed/plain/commit/db882e6d47))
- CSRF exception messages now include more detailed context about what was rejected and why (e.g., port mismatches, host mismatches) ([9a8e09c](https://github.com/dropseed/plain/commit/9a8e09c1dc))
- The `plain agent md` command now saves a combined `AGENTS.md` file to `.plain/` by default when using `plain dev`, making it easier to provide context to coding agents ([786b7a0](https://github.com/dropseed/plain/commit/786b7a0ca1))
- CLI help text styling has been refined with dimmed descriptions and usage prefixes for improved readability ([d7f7053](https://github.com/dropseed/plain/commit/d7f705398d))

### Upgrade instructions

- No changes required

## [0.84.1](https://github.com/dropseed/plain/releases/plain@0.84.1) (2025-10-31)

### What's changed

- Added `license = "BSD-3-Clause"` to package metadata in `pyproject.toml` ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.84.0](https://github.com/dropseed/plain/releases/plain@0.84.0) (2025-10-29)

### What's changed

- The `DEFAULT_RESPONSE_HEADERS` setting now supports format string placeholders (e.g., `{request.csp_nonce}`) for dynamic header values instead of requiring a callable function ([5199383128](https://github.com/dropseed/plain/commit/5199383128))
- Views can now set headers to `None` to explicitly remove default response headers ([5199383128](https://github.com/dropseed/plain/commit/5199383128))
- Added comprehensive documentation for customizing default response headers including override, remove, and extend patterns ([5199383128](https://github.com/dropseed/plain/commit/5199383128))

### Upgrade instructions

- If you have `DEFAULT_RESPONSE_HEADERS` configured as a callable function, convert it to a dictionary with format string placeholders:

    ```python
    # Before:
    def DEFAULT_RESPONSE_HEADERS(request):
        nonce = request.csp_nonce
        return {
            "Content-Security-Policy": f"script-src 'self' 'nonce-{nonce}'",
        }

    # After:
    DEFAULT_RESPONSE_HEADERS = {
        "Content-Security-Policy": "script-src 'self' 'nonce-{request.csp_nonce}'",
    }
    ```

- If you were overriding default headers to empty strings (`""`) to remove them, change those to `None` instead

## [0.83.0](https://github.com/dropseed/plain/releases/plain@0.83.0) (2025-10-29)

### What's changed

- Added comprehensive Content Security Policy (CSP) documentation explaining how to use nonces with inline scripts and styles ([784f3dd972](https://github.com/dropseed/plain/commit/784f3dd972))
- The `json_script` utility function now accepts an optional `nonce` parameter for CSP-compliant inline JSON scripts ([784f3dd972](https://github.com/dropseed/plain/commit/784f3dd972))

### Upgrade instructions

- Any `|json_script` usages need to make sure the second argument is a nonce, not a custom encoder (which is now third)

## [0.82.0](https://github.com/dropseed/plain/releases/plain@0.82.0) (2025-10-29)

### What's changed

- The `DEFAULT_RESPONSE_HEADERS` setting can now be a callable that accepts a request argument, enabling dynamic header generation per request ([cb92905834](https://github.com/dropseed/plain/commit/cb92905834))
- Added `request.csp_nonce` cached property for generating Content Security Policy nonces ([75071dcc70](https://github.com/dropseed/plain/commit/75071dcc70))
- Simplified the preflight command by moving `plain preflight check` back to `plain preflight` ([40c2c4560e](https://github.com/dropseed/plain/commit/40c2c4560e))

### Upgrade instructions

- If you use `plain preflight check`, update to `plain preflight` (the `check` subcommand has been removed for simplicity)
- If you use `plain preflight check --deploy`, update to `plain preflight --deploy`

## [0.81.0](https://github.com/dropseed/plain/releases/plain@0.81.0) (2025-10-22)

### What's changed

- Removed support for category-specific error template fallbacks like `4xx.html` and `5xx.html` ([9513f7c4fa](https://github.com/dropseed/plain/commit/9513f7c4fa))

### Upgrade instructions

- If you have `4xx.html` or `5xx.html` error templates, rename them to specific status code templates (e.g., `404.html`, `500.html`) or remove them if you prefer the plain HTTP response fallback

## [0.80.0](https://github.com/dropseed/plain/releases/plain@0.80.0) (2025-10-22)

### What's changed

- CSRF failures now raise `SuspiciousOperation` (HTTP 400) instead of `PermissionDenied` (HTTP 403) ([ad146bde3e](https://github.com/dropseed/plain/commit/ad146bde3e))
- Error templates can now use category-specific fallbacks like `4xx.html` or `5xx.html` instead of the generic `error.html` ([716cfa3cfc](https://github.com/dropseed/plain/commit/716cfa3cfc))
- Updated error template documentation with best practices for self-contained `500.html` templates ([55cea3b522](https://github.com/dropseed/plain/commit/55cea3b522))

### Upgrade instructions

- If you have a `templates/error.html` template, instead create specific error templates for each status code you want to customize (e.g., `400.html`, `403.html`, `404.html`, `500.html`). You can also create category-specific templates like `4xx.html` or `5xx.html` for broader coverage.

## [0.79.0](https://github.com/dropseed/plain/releases/plain@0.79.0) (2025-10-22)

### What's changed

- Response objects now have an `exception` attribute that stores the exception that caused 5xx errors ([0a243ba89c](https://github.com/dropseed/plain/commit/0a243ba89c))
- Middleware classes now use an abstract base class `HttpMiddleware` with a `process_request()` method ([b960eed6c6](https://github.com/dropseed/plain/commit/b960eed6c6))
- CSRF middleware now raises `PermissionDenied` instead of rendering a custom `CsrfFailureView` ([d4b93e59b3](https://github.com/dropseed/plain/commit/d4b93e59b3))
- The `HTTP_ERROR_VIEWS` setting has been removed ([7a4e3a31f4](https://github.com/dropseed/plain/commit/7a4e3a31f4))
- Standalone `plain-changelog` and `plain-upgrade` executables have been removed in favor of the built-in commands ([07c3a4c540](https://github.com/dropseed/plain/commit/07c3a4c540))
- Standalone `plain-build` executable has been removed ([99301ea797](https://github.com/dropseed/plain/commit/99301ea797))
- Removed automatic logging of all HTTP 400+ status codes for cleaner logs ([c2769d7281](https://github.com/dropseed/plain/commit/c2769d7281))

### Upgrade instructions

- If you have custom middleware, inherit from `HttpMiddleware` and rename your `__call__()` method to `process_request()`:

    ```python
    # Before:
    class MyMiddleware:
        def __init__(self, get_response):
            self.get_response = get_response

        def __call__(self, request):
            response = self.get_response(request)
            return response

    # After:
    from plain.http import HttpMiddleware

    class MyMiddleware(HttpMiddleware):
        def process_request(self, request):
            response = self.get_response(request)
            return response
    ```

- Remove any custom `HTTP_ERROR_VIEWS` setting from your configuration - error views are now controlled entirely by exception handlers
- If you were calling `plain-changelog` or `plain-upgrade` as standalone commands, use `plain changelog` or `plain upgrade` instead
- If you were calling `plain-build` as a standalone command, use `plain build` instead

## [0.78.2](https://github.com/dropseed/plain/releases/plain@0.78.2) (2025-10-20)

### What's changed

- Updated package metadata to use `[dependency-groups]` instead of `[tool.uv]` for development dependencies, following PEP 735 standard ([1b43a3a272](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.78.1](https://github.com/dropseed/plain/releases/plain@0.78.1) (2025-10-17)

### What's changed

- Fixed job worker logging by using `getLogger` instead of directly instantiating `Logger` for the plain logger ([dd675666b9](https://github.com/dropseed/plain/commit/dd675666b9))

### Upgrade instructions

- No changes required

## [0.78.0](https://github.com/dropseed/plain/releases/plain@0.78.0) (2025-10-17)

### What's changed

- Chores have been refactored to use abstract base classes instead of decorated functions ([c4466d3c60](https://github.com/dropseed/plain/commit/c4466d3c60))
- Added `SHELL_IMPORT` setting to customize what gets automatically imported in `plain shell` ([9055f59c08](https://github.com/dropseed/plain/commit/9055f59c08))
- Views that return `None` now raise `Http404` instead of returning `ResponseNotFound` ([5bb60016eb](https://github.com/dropseed/plain/commit/5bb60016eb))
- The `plain chores list` command output formatting now matches the `plain jobs list` format ([4b6881a49e](https://github.com/dropseed/plain/commit/4b6881a49e))

### Upgrade instructions

- Update any chores from decorated functions to class-based chores:

    ```python
    # Before:
    @register_chore("group")
    def chore_name():
        """Description"""
        return "Done!"

    # After:
    from plain.chores import Chore, register_chore

    @register_chore
    class ChoreName(Chore):
        """Description"""

        def run(self):
            return "Done!"
    ```

- Import `Chore` base class from `plain.chores` when creating new chores

## [0.77.0](https://github.com/dropseed/plain/releases/plain@0.77.0) (2025-10-13)

### What's changed

- The `plain server --reload` now uses `watchfiles` for improved cross-platform file watching ([92e95c5032](https://github.com/dropseed/plain/commit/92e95c5032))
- Server reloader now watches `.env*` files for changes and triggers automatic reload ([92e95c5032](https://github.com/dropseed/plain/commit/92e95c5032))
- HTML template additions and deletions now trigger automatic server reload when using `--reload` ([f2f31c288b](https://github.com/dropseed/plain/commit/f2f31c288b))
- Internal server worker type renamed from "gthread" to "thread" for clarity ([6470748e91](https://github.com/dropseed/plain/commit/6470748e91))

### Upgrade instructions

- No changes required

## [0.76.0](https://github.com/dropseed/plain/releases/plain@0.76.0) (2025-10-12)

### What's changed

- Added new `plain server` command with built-in WSGI server (vendored gunicorn) ([f9dc2867c7](https://github.com/dropseed/plain/commit/f9dc2867c7))
- The `plain server` command supports `WEB_CONCURRENCY` environment variable for worker processes ([0c3e8c6f32](https://github.com/dropseed/plain/commit/0c3e8c6f32))
- Simplified server startup logging to use a single consolidated log line ([b1405b71f0](https://github.com/dropseed/plain/commit/b1405b71f0))
- Removed `gunicorn` as an external dependency - server functionality is now built into plain core ([cb6c2f484d](https://github.com/dropseed/plain/commit/cb6c2f484d))
- Internal server environment variables renamed from `GUNICORN_*` to `PLAIN_SERVER_*` ([745c073123](https://github.com/dropseed/plain/commit/745c073123))
- Removed unused server features including hooks, syslog, proxy protocol, user/group dropping, and config file loading ([be0f82d92b](https://github.com/dropseed/plain/commit/be0f82d92b), [10c206875b](https://github.com/dropseed/plain/commit/10c206875b), [ecf327014c](https://github.com/dropseed/plain/commit/ecf327014c), [fb5a10f50b](https://github.com/dropseed/plain/commit/fb5a10f50b))

### Upgrade instructions

- Replace any direct usage of `gunicorn` with the new `plain server` command (ex. `gunicorn plain.wsgi:app --workers 4` becomes `plain server --workers 4`)
- Update any deployment scripts or Procfiles that use `gunicorn` to use `plain server` instead
- Remove `gunicorn` from your project dependencies if you added it separately (it's now built into plain)
- For Heroku deployments, the `$PORT` is not automatically detected - update your Procfile to `web: plain server --bind 0.0.0.0:$PORT`
- If you were using gunicorn configuration files, migrate the settings to `plain server` command-line options (run `plain server --help` to see available options)

## [0.75.0](https://github.com/dropseed/plain/releases/plain@0.75.0) (2025-10-10)

### What's changed

- Documentation references updated from `plain-worker` to `plain-jobs` following the package rename ([24219856e0](https://github.com/dropseed/plain/commit/24219856e0))

### Upgrade instructions

- No changes required

## [0.74.0](https://github.com/dropseed/plain/releases/plain@0.74.0) (2025-10-08)

### What's changed

- The `plain agent request` command now displays request ID in the response output ([4a20cfa3fc](https://github.com/dropseed/plain/commit/4a20cfa3fc))
- Request headers are now included in OpenTelemetry tracing baggage for improved observability ([08a3376d06](https://github.com/dropseed/plain/commit/08a3376d06))

### Upgrade instructions

- No changes required

## [0.73.0](https://github.com/dropseed/plain/releases/plain@0.73.0) (2025-10-07)

### What's changed

- Internal preflight result handling updated to use `model_options` instead of `_meta` for model label retrieval ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.72.2](https://github.com/dropseed/plain/releases/plain@0.72.2) (2025-10-06)

### What's changed

- Improved type annotations for test client responses with new `ClientResponse` wrapper class ([369353f9d6](https://github.com/dropseed/plain/commit/369353f9d6))
- Enhanced internal type checking for WSGI handler and request/response types ([50463b00c3](https://github.com/dropseed/plain/commit/50463b00c3))

### Upgrade instructions

- No changes required

## [0.72.1](https://github.com/dropseed/plain/releases/plain@0.72.1) (2025-10-02)

### What's changed

- Fixed documentation examples to use the correct view attribute names (`self.user` instead of `self.request.user`) ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.72.0](https://github.com/dropseed/plain/releases/plain@0.72.0) (2025-10-02)

### What's changed

- Request attributes `user` and `session` are no longer set directly on the request object ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Test client now uses `plain.auth.requests.get_request_user()` to retrieve user for response object when available ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Removed `plain.auth.middleware.AuthenticationMiddleware` from default middleware configuration ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- No changes required

## [0.71.0](https://github.com/dropseed/plain/releases/plain@0.71.0) (2025-09-30)

### What's changed

- Renamed `HttpRequest` to `Request` throughout the codebase for consistency and simplicity ([cd46ff20](https://github.com/dropseed/plain/commit/cd46ff2003))
- Renamed `HttpHeaders` to `RequestHeaders` for naming consistency ([cd46ff20](https://github.com/dropseed/plain/commit/cd46ff2003))
- Renamed settings: `APP_NAME` → `NAME`, `APP_VERSION` → `VERSION`, `APP_LOG_LEVEL` → `LOG_LEVEL`, `APP_LOG_FORMAT` → `LOG_FORMAT`, `PLAIN_LOG_LEVEL` → `FRAMEWORK_LOG_LEVEL` ([4c5f2166](https://github.com/dropseed/plain/commit/4c5f2166c1))
- Added `request.get_preferred_type()` method to select the most preferred media type from Accept header ([b105ba4d](https://github.com/dropseed/plain/commit/b105ba4dd0))
- Moved helper functions in `http/request.py` to be static methods of `QueryDict` ([0e1b0133](https://github.com/dropseed/plain/commit/0e1b0133c5))

### Upgrade instructions

- Replace all imports and usage of `HttpRequest` with `Request`
- Replace all imports and usage of `HttpHeaders` with `RequestHeaders`
- Update any custom settings that reference `APP_NAME` to `NAME`, `APP_VERSION` to `VERSION`, `APP_LOG_LEVEL` to `LOG_LEVEL`, `APP_LOG_FORMAT` to `LOG_FORMAT`, and `PLAIN_LOG_LEVEL` to `FRAMEWORK_LOG_LEVEL`
- Configuring these settings via the `PLAIN_` prefixed environment variable will need to be updated accordingly

## [0.70.0](https://github.com/dropseed/plain/releases/plain@0.70.0) (2025-09-30)

### What's changed

- Added comprehensive type annotations throughout the codebase for improved IDE support and type checking ([365414c](https://github.com/dropseed/plain/commit/365414cc6f))
- The `Asset` class in `plain.assets.finders` is now a module-level public class instead of being defined inside `iter_assets()` ([6321765](https://github.com/dropseed/plain/commit/6321765d30))

### Upgrade instructions

- No changes required

## [0.69.0](https://github.com/dropseed/plain/releases/plain@0.69.0) (2025-09-29)

### What's changed

- Model-related exceptions (`FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, `FullResultSet`) moved from `plain.exceptions` to `plain.models.exceptions` ([1c02564](https://github.com/dropseed/plain/commit/1c02564561))
- Added `plain dev` alias prompt that suggests adding `p` as a shell alias for convenience ([d913b44](https://github.com/dropseed/plain/commit/d913b44fab))

### Upgrade instructions

- Replace imports of `FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, or `FullResultSet` from `plain.exceptions` to `plain.models.exceptions`
- If you're using `ObjectDoesNotExist` in views, update your import from `plain.exceptions.ObjectDoesNotExist` to `plain.models.exceptions.ObjectDoesNotExist`

## [0.68.1](https://github.com/dropseed/plain/releases/plain@0.68.1) (2025-09-25)

### What's changed

- Preflight checks are now sorted by name for consistent ordering ([cb8e160](https://github.com/dropseed/plain/commit/cb8e160934))

### Upgrade instructions

- No changes required

## [0.68.0](https://github.com/dropseed/plain/releases/plain@0.68.0) (2025-09-25)

### What's changed

- Major refactor of the preflight check system with new CLI commands and improved output ([b0b610d461](https://github.com/dropseed/plain/commit/b0b610d461))
- Preflight checks now use descriptive IDs instead of numeric codes ([cd96c97b25](https://github.com/dropseed/plain/commit/cd96c97b25))
- Unified preflight error messages and hints into a single `fix` field ([c7cde12149](https://github.com/dropseed/plain/commit/c7cde12149))
- Added `plain-upgrade` as a standalone command for upgrading Plain packages ([42f2eed80c](https://github.com/dropseed/plain/commit/42f2eed80c))

### Upgrade instructions

- Update any uses of the `plain preflight` command to `plain preflight check`, and remove the `--database` and `--fail-level` options which no longer exist
- Custom preflight checks should be class based, extending `PreflightCheck` and implementing the `run()` method
- Preflight checks need to be registered with a custom name (ex. `@register_check("app.my_custom_check")`) and optionally with `deploy=True` if it should run in only in deploy mode
- Preflight results should use `PreflightResult` (optionally with `warning=True`) instead of `preflight.Warning` or `preflight.Error`
- Preflight result IDs should be descriptive strings (e.g., `models.lazy_reference_resolution_failed`) instead of numeric codes
- `PREFLIGHT_SILENCED_CHECKS` setting has been replaced with `PREFLIGHT_SILENCED_RESULTS` which should contain a list of result IDs to silence. `PREFLIGHT_SILENCED_CHECKS` now silences entire checks by name.

## [0.67.0](https://github.com/dropseed/plain/releases/plain@0.67.0) (2025-09-22)

### What's changed

- `ALLOWED_HOSTS` now defaults to `[]` (empty list) which allows all hosts, making it easier for development setups ([d3cb7712b9](https://github.com/dropseed/plain/commit/d3cb7712b9))
- Empty `ALLOWED_HOSTS` in production now triggers a preflight error instead of a warning to ensure proper security configuration ([d3cb7712b9](https://github.com/dropseed/plain/commit/d3cb7712b9))

### Upgrade instructions

- No changes required

## [0.66.0](https://github.com/dropseed/plain/releases/plain@0.66.0) (2025-09-22)

### What's changed

- Host validation moved to dedicated middleware and `ALLOWED_HOSTS` setting is now required ([6a4b7be](https://github.com/dropseed/plain/commit/6a4b7be220))
- Changed `request.get_port()` method to `request.port` cached property ([544f3e1](https://github.com/dropseed/plain/commit/544f3e19f8))
- Removed internal `request._get_full_path()` method ([50cdb58](https://github.com/dropseed/plain/commit/50cdb58d4e))

### Upgrade instructions

- Add `ALLOWED_HOSTS` setting to your configuration if not already present (required for host validation)
- Replace any usage of `request.get_host()` with `request.host`
- Replace any usage of `request.get_port()` with `request.port`

## [0.65.1](https://github.com/dropseed/plain/releases/plain@0.65.1) (2025-09-22)

### What's changed

- Fixed DisallowedHost exception handling in request span attributes to prevent telemetry errors ([bcc0005](https://github.com/dropseed/plain/commit/bcc000575b))
- Removed cached property optimization for scheme/host to improve request processing reliability ([3a52690](https://github.com/dropseed/plain/commit/3a52690d47))

### Upgrade instructions

- No changes required

## [0.65.0](https://github.com/dropseed/plain/releases/plain@0.65.0) (2025-09-22)

### What's changed

- Added CIDR notation support to `ALLOWED_HOSTS` for IP address range validation ([c485d21](https://github.com/dropseed/plain/commit/c485d21a8b))

### Upgrade instructions

- No changes required

## [0.64.0](https://github.com/dropseed/plain/releases/plain@0.64.0) (2025-09-19)

### What's changed

- Added `plain-build` command as a standalone executable ([4b39ca4](https://github.com/dropseed/plain/commit/4b39ca4599))
- Removed `constant_time_compare` utility function in favor of `hmac.compare_digest` ([55f3f55](https://github.com/dropseed/plain/commit/55f3f5596d))
- CLI now forces colors in CI environments (GitHub Actions, GitLab CI, etc.) for better output visibility ([56f7d2b](https://github.com/dropseed/plain/commit/56f7d2b312))

### Upgrade instructions

- Replace any usage of `plain.utils.crypto.constant_time_compare` with `hmac.compare_digest` or `secrets.compare_digest`

## [0.63.0](https://github.com/dropseed/plain/releases/plain@0.63.0) (2025-09-12)

### What's changed

- Model manager attribute renamed from `objects` to `query` throughout codebase ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Simplified HTTPS redirect middleware by removing `HTTPS_REDIRECT_EXEMPT_PATHS` and `HTTPS_REDIRECT_HOST` settings ([d264cd3](https://github.com/dropseed/plain/commit/d264cd306b))
- Database backups are now created automatically during migrations when `DEBUG=True` unless explicitly disabled ([c802307](https://github.com/dropseed/plain/commit/c8023074e9))

### Upgrade instructions

- Remove any `HTTPS_REDIRECT_EXEMPT_PATHS` and `HTTPS_REDIRECT_HOST` settings from your configuration - the HTTPS redirect middleware now performs a blanket redirect. For advanced redirect logic, write custom middleware.

## [0.62.1](https://github.com/dropseed/plain/releases/plain@0.62.1) (2025-09-09)

### What's changed

- Added clarification about `app_logger.kv` removal to 0.62.0 changelog ([106636f](https://github.com/dropseed/plain/commit/106636fca6))

### Upgrade instructions

- No changes required

## [0.62.0](https://github.com/dropseed/plain/releases/plain@0.62.0) (2025-09-09)

### What's changed

- Complete rewrite of logging settings and AppLogger with improved formatters and debug capabilities ([ea7c953](https://github.com/dropseed/plain/commit/ea7c9537e3))
- Added `app_logger.debug_mode()` context manager to temporarily change log level ([f535459](https://github.com/dropseed/plain/commit/f53545f9fa))
- Minimum Python version updated to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Removed `app_logger.kv` in favor of context kwargs ([ea7c953](https://github.com/dropseed/plain/commit/ea7c9537e3))

### Upgrade instructions

- Make sure you are using Python 3.13 or higher
- Replace any `app_logger.kv.info("message", key=value)` calls with `app_logger.info("message", key=value)` or appropriate log level

## [0.61.0](https://github.com/dropseed/plain/releases/plain@0.61.0) (2025-09-03)

### What's changed

- Added new `plain agent` command with subcommands for coding agents including `docs`, `md`, and `request` ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))
- Added `-c` option to `plain shell` to execute commands and exit, similar to `python -c` ([5e67f0b](https://github.com/dropseed/plain/commit/5e67f0bcd8))
- The `plain docs --llm` functionality has been moved to `plain agent docs` command ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))
- Removed the `plain help` command in favor of standard `plain --help` ([df3edbf](https://github.com/dropseed/plain/commit/df3edbf0bd))

### Upgrade instructions

- Replace `plain docs --llm` usage with `plain agent docs` command
- Use `plain --help` instead of `plain help` command

## [0.60.0](https://github.com/dropseed/plain/releases/plain@0.60.0) (2025-08-27)

### What's changed

- Added new `APP_VERSION` setting that defaults to the project version from `pyproject.toml` ([57fb948d46](https://github.com/dropseed/plain/commit/57fb948d46))
- Updated `get_app_name_from_pyproject()` to `get_app_info_from_pyproject()` to return both name and version ([57fb948d46](https://github.com/dropseed/plain/commit/57fb948d46))

### Upgrade instructions

- No changes required

## [0.59.0](https://github.com/dropseed/plain/releases/plain@0.59.0) (2025-08-22)

### What's changed

- Added new `APP_NAME` setting that defaults to the project name from `pyproject.toml` ([1a4d60e](https://github.com/dropseed/plain/commit/1a4d60e787))
- Template views now validate that `get_template_names()` returns a list instead of a string ([428a64f](https://github.com/dropseed/plain/commit/428a64f8cc))
- Object views now use cached properties for `.object` and `.objects` to improve performance ([bd0507a](https://github.com/dropseed/plain/commit/bd0507a72c))
- Improved `plain upgrade` command to suggest using subagents when there are more than 3 package updates ([497c30d](https://github.com/dropseed/plain/commit/497c30d445))

### Upgrade instructions

- In object views, `self.load_object()` is no longer necessary as `self.object` is now a cached property.

## [0.58.0](https://github.com/dropseed/plain/releases/plain@0.58.0) (2025-08-19)

### What's changed

- Complete rewrite of CSRF protection using modern Sec-Fetch-Site headers and origin validation ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Replaced CSRF view mixin with path-based exemptions using `CSRF_EXEMPT_PATHS` setting ([2a50a9154e](https://github.com/dropseed/plain/commit/2a50a9154e))
- Renamed `HTTPS_REDIRECT_EXEMPT` to `HTTPS_REDIRECT_EXEMPT_PATHS` with leading slash requirement ([b53d3bb7a7](https://github.com/dropseed/plain/commit/b53d3bb7a7))
- Agent commands now print prompts directly when running in Claude Code or Codex Sandbox environments ([6eaed8ae3b](https://github.com/dropseed/plain/commit/6eaed8ae3b))

### Upgrade instructions

- Remove any usage of `CsrfExemptViewMixin` and `request.csrf_exempt` and add exempt paths to the `CSRF_EXEMPT_PATHS` setting instead (ex. `CSRF_EXEMPT_PATHS = [r"^/api/", r"/webhooks/.*"]` -- but consider first whether the view still needs CSRF exemption under the new implementation)
- Replace `HTTPS_REDIRECT_EXEMPT` with `HTTPS_REDIRECT_EXEMPT_PATHS` and ensure patterns include leading slash (ex. `[r"^/health$", r"/api/internal/.*"]`)
- Remove all CSRF cookie and token related settings - the new implementation doesn't use cookies or tokens (ex. `{{ csrf_input }}` and `{{ csrf_token }}`)

## [0.57.0](https://github.com/dropseed/plain/releases/plain@0.57.0) (2025-08-15)

### What's changed

- The `ResponsePermanentRedirect` class has been removed; use `ResponseRedirect` with `status_code=301` instead ([d5735ea](https://github.com/dropseed/plain/commit/d5735ea4f8))
- The `RedirectView.permanent` attribute has been replaced with `status_code` for more flexible redirect status codes ([12dda16](https://github.com/dropseed/plain/commit/12dda16731))
- Updated `RedirectView` initialization parameters: `url_name` replaces `pattern_name`, `preserve_query_params` replaces `query_string`, and removed 410 Gone functionality ([3b9ca71](https://github.com/dropseed/plain/commit/3b9ca713bf))

### Upgrade instructions

- Replace `ResponsePermanentRedirect` imports with `ResponseRedirect` and pass `status_code=301` to the constructor
- Update `RedirectView` subclasses to use `status_code=301` instead of `permanent=True`
- Replace `pattern_name` with `url_name` in RedirectView usage
- Replace `query_string=True` with `preserve_query_params=True` in RedirectView usage

## [0.56.1](https://github.com/dropseed/plain/releases/plain@0.56.1) (2025-07-30)

### What's changed

- Improved `plain install` command instructions to be more explicit about completing code modifications ([83292225db](https://github.com/dropseed/plain/commit/83292225db))

### Upgrade instructions

- No changes required

## [0.56.0](https://github.com/dropseed/plain/releases/plain@0.56.0) (2025-07-25)

### What's changed

- Added `plain install` command to install Plain packages with agent-assisted setup ([bf1873e](https://github.com/dropseed/plain/commit/bf1873eb81))
- Added `--print` option to agent commands (`plain install` and `plain upgrade`) to print prompts without running the agent ([9721331](https://github.com/dropseed/plain/commit/9721331e40))
- The `plain docs` command now automatically converts hyphens to dots in package names (e.g., `plain-models` → `plain.models`) ([1e3edc1](https://github.com/dropseed/plain/commit/1e3edc10f7))
- Moved `plain-upgrade` functionality into plain core, eliminating the need for a separate package ([473f9bb](https://github.com/dropseed/plain/commit/473f9bb718))

### Upgrade instructions

- No changes required

## [0.55.0](https://github.com/dropseed/plain/releases/plain@0.55.0) (2025-07-22)

### What's changed

- Updated URL pattern documentation examples to use `id` instead of `pk` in URL kwargs ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6e4e))
- Updated views documentation examples to use `id` instead of `pk` for DetailView, UpdateView, and DeleteView ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6e4e))

### Upgrade instructions

- Update your URL patterns from `<int:pk>` to `<int:id>` in your URLconf
- Update view code that accesses `self.url_kwargs["pk"]` to use `self.url_kwargs["id"]` instead
- Replace any QuerySet filters using `pk` with `id` (e.g., `Model.query.get(pk=1)` becomes `Model.query.get(id=1)`)

## [0.54.1](https://github.com/dropseed/plain/releases/plain@0.54.1) (2025-07-20)

### What's changed

- Fixed OpenTelemetry route naming to include leading slash for consistency with HTTP paths ([9d77268](https://github.com/dropseed/plain/commit/9d77268988))

### Upgrade instructions

- No changes required

## [0.54.0](https://github.com/dropseed/plain/releases/plain@0.54.0) (2025-07-18)

### What's changed

- Added OpenTelemetry instrumentation for HTTP requests, views, and template rendering ([b0224d0418](https://github.com/dropseed/plain/commit/b0224d0418))
- Added `plain-observer` package reference to plain README ([f29ff4dafe](https://github.com/dropseed/plain/commit/f29ff4dafe))

### Upgrade instructions

- No changes required

## [0.53.0](https://github.com/dropseed/plain/releases/plain@0.53.0) (2025-07-18)

### What's changed

- Added a `pluralize` filter for Jinja templates to handle singular/plural forms ([4cef9829ed](https://github.com/dropseed/plain/commit/4cef9829ed))
- Added `get_signed_cookie()` method to `HttpRequest` for retrieving and verifying signed cookies ([f8796c8786](https://github.com/dropseed/plain/commit/f8796c8786))
- Improved CLI error handling by using `click.UsageError` instead of manual error printing ([88f06c5184](https://github.com/dropseed/plain/commit/88f06c5184))
- Simplified preflight check success message ([adffc06152](https://github.com/dropseed/plain/commit/adffc06152))

### Upgrade instructions

- No changes required

## [0.52.2](https://github.com/dropseed/plain/releases/plain@0.52.2) (2025-06-27)

### What's changed

- Improved documentation for the assets subsystem: the `AssetsRouter` reference in the Assets README now links directly to the source code for quicker navigation ([65437e9](https://github.com/dropseed/plain/commit/65437e9bb1a522c7ababe0fc195f63bc5fd6c4d4))

### Upgrade instructions

- No changes required

## [0.52.1](https://github.com/dropseed/plain/releases/plain@0.52.1) (2025-06-27)

### What's changed

- Fixed `plain help` output on newer versions of Click by switching from `MultiCommand` to `Group` when determining sub-commands ([9482e42](https://github.com/dropseed/plain/commit/9482e421ac408ac043d341edda3dba9f27694f08))

### Upgrade instructions

- No changes required

## [0.52.0](https://github.com/dropseed/plain/releases/plain@0.52.0) (2025-06-26)

### What's changed

- Added `plain-changelog` as a standalone executable so you can view changelogs without importing the full framework ([e4e7324](https://github.com/dropseed/plain/commit/e4e7324cd284c800ff957933748d6639615cbea6))
- Removed the runtime dependency on the `packaging` library by replacing it with an internal version-comparison helper ([e4e7324](https://github.com/dropseed/plain/commit/e4e7324cd284c800ff957933748d6639615cbea6))
- Improved the error message when a package changelog cannot be found, now showing the path that was looked up ([f3c82bb](https://github.com/dropseed/plain/commit/f3c82bb59e07c1bddbdb2557f2043e039c1cd1e9))
- Fixed an f-string issue that broke `plain.debug.dd` on Python 3.11 ([ed24276](https://github.com/dropseed/plain/commit/ed24276a12191e4c8903369002dd32b69eb358b3))

### Upgrade instructions

- No changes required

## [0.51.0](https://github.com/dropseed/plain/releases/plain@0.51.0) (2025-06-24)

### What's changed

- New `plain changelog` CLI sub-command to quickly view a package’s changelog from the terminal. Supports `--from`/`--to` flags to limit the version range ([50f0de7](https://github.com/dropseed/plain/commit/50f0de721f263ec6274852bd8838f4e5037b27dc)).

### Upgrade instructions

- No changes required

## [0.50.0](https://github.com/dropseed/plain/releases/plain@0.50.0) (2025-06-23)

### What's changed

- The URL inspection command has moved; run `plain urls list` instead of the old `plain urls` command ([6146fcb](https://github.com/dropseed/plain/commit/6146fcba536c551277d625bd750c385431ea18eb))
- `plain preflight` gains a simpler `--database` flag that enables database checks for your default database. The previous behaviour that accepted one or more database aliases has been removed ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572))
- Settings overhaul: use a single `DATABASE` setting instead of `DATABASES`/`DATABASE_ROUTERS` ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572))

### Upgrade instructions

- Update any scripts or documentation that call `plain urls …`:
    - Replace `plain urls --flat` with `plain urls list --flat`
- If you invoke preflight checks in CI or locally:
    - Replace `plain preflight --database <alias>` (or multiple aliases) with the new boolean flag: `plain preflight --database`
- In `settings.py` migrate to the new database configuration:

    ```python
    # Before
    DATABASES = {
        "default": {
            "ENGINE": "plain.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

    # After
    DATABASE = {
        "ENGINE": "plain.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
    ```

    Remove any `DATABASES` and `DATABASE_ROUTERS` settings – they are no longer read.
