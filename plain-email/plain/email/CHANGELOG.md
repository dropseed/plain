# plain-email changelog

## [0.19.0](https://github.com/dropseed/plain/releases/plain-email@0.19.0) (2026-04-24)

### What's changed

- **Added a preview email backend** (`plain.email.backends.preview.EmailBackend`) that captures sent messages as `.eml` files in `.plain/emails/` instead of delivering them. When `plain.toolbar` is installed, the toolbar gains an **Email** panel that lists recent captured messages and renders their HTML bodies inline; `.eml` files can also be opened directly in Mail.app. ([9c3cef100997](https://github.com/dropseed/plain/commit/9c3cef100997))
- Fixed a stale backend count in the README. ([c487206dc3db](https://github.com/dropseed/plain/commit/c487206dc3db))

### Upgrade instructions

- No changes required. To use the new preview backend in development, set `EMAIL_BACKEND = "plain.email.backends.preview.EmailBackend"` (or `PLAIN_EMAIL_BACKEND=plain.email.backends.preview.EmailBackend`).

## [0.18.2](https://github.com/dropseed/plain/releases/plain-email@0.18.2) (2026-04-13)

### What's changed

- Migrated type suppression comments to `ty: ignore` for the new ty checker version. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- No changes required.

## [0.18.1](https://github.com/dropseed/plain/releases/plain-email@0.18.1) (2026-04-05)

### What's changed

- **Added OTel tracing to the SMTP email backend.** Each `_send()` call now creates an `email.send` CLIENT span with `email.system`, `email.recipients.count`, `email.has_attachments`, `server.address`, and `server.port` attributes. SMTP errors set `error.type` on the span. No PII (addresses, subjects) is recorded. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))

### Upgrade instructions

- No changes required.

## [0.18.0](https://github.com/dropseed/plain/releases/plain-email@0.18.0) (2026-03-20)

### What's changed

- **Removed `auth_user` and `auth_password` parameters** from `send_mail()` and `send_mass_mail()` — these functions now always use the `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` settings for authentication. Use `get_connection(username=..., password=...)` and pass the connection directly if you need custom credentials ([99c9e751e8](https://github.com/dropseed/plain/commit/99c9e751e8))

### Upgrade instructions

- Remove any `auth_user` or `auth_password` arguments from `send_mail()` and `send_mass_mail()` calls.
- If you need custom SMTP credentials per-call, create a connection with `get_connection(username=..., password=...)` and pass it via the `connection` parameter instead.

## [0.17.0](https://github.com/dropseed/plain/releases/plain-email@0.17.0) (2026-03-12)

### What's changed

- **Removed file-based email backend** — the `plain.email.backends.filebased.EmailBackend` has been removed along with the `EMAIL_FILE_PATH` setting. Use the console backend for local development instead ([b0bfb96a7d27](https://github.com/dropseed/plain/commit/b0bfb96a7d27))

### Upgrade instructions

- If you were using `EMAIL_BACKEND = "plain.email.backends.filebased.EmailBackend"`, switch to the console backend: `EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"`
- Remove any `EMAIL_FILE_PATH` setting from your configuration.

## [0.16.1](https://github.com/dropseed/plain/releases/plain-email@0.16.1) (2026-03-10)

### What's changed

- Removed `type: ignore` comment on `EMAIL_HOST_PASSWORD` default value, now that `Secret` is type-transparent ([997afd9a558f](https://github.com/dropseed/plain/commit/997afd9a558f))

### Upgrade instructions

- No changes required.

## [0.16.0](https://github.com/dropseed/plain/releases/plain-email@0.16.0) (2026-03-10)

### What's changed

- **Removed `fail_silently` parameter** from `get_connection()`, `send_mail()`, `send_mass_mail()`, and `BaseEmailBackend.__init__()` — email errors now always raise exceptions instead of being silently swallowed ([d08315532ace](https://github.com/dropseed/plain/commit/d08315532ace))
- **`BaseEmailBackend.open()` return type changed** from `bool | None` to `bool` ([d08315532ace](https://github.com/dropseed/plain/commit/d08315532ace))
- Simplified console and file-based email backends by removing try/except wrappers that relied on `fail_silently` ([d08315532ace](https://github.com/dropseed/plain/commit/d08315532ace))
- Cleaned up backend `__init__` signatures — removed `**kwargs` passthrough and unused `Any` imports ([d08315532ace](https://github.com/dropseed/plain/commit/d08315532ace))

### Upgrade instructions

- Remove any `fail_silently=True/False` arguments from `send_mail()`, `send_mass_mail()`, and `get_connection()` calls.
- If you have a custom email backend subclass, remove `fail_silently` from `__init__` and update `open()` to return `bool` instead of `bool | None`.

## [0.15.4](https://github.com/dropseed/plain/releases/plain-email@0.15.4) (2026-02-28)

### What's changed

- Replaced references to the removed `DEFAULT_CHARSET` setting with hardcoded `"utf-8"` in SMTP backend and message encoding ([901e6b3c49](https://github.com/dropseed/plain/commit/901e6b3c49))

### Upgrade instructions

- No changes required.

## [0.15.3](https://github.com/dropseed/plain/releases/plain-email@0.15.3) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.15.2](https://github.com/dropseed/plain/releases/plain-email@0.15.2) (2026-02-04)

### What's changed

- Added `__all__` export to `backends/base` module ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Removed `@internalcode` decorator from internal MIME helper classes ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- No changes required.

## [0.15.1](https://github.com/dropseed/plain/releases/plain-email@0.15.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.15.0](https://github.com/dropseed/plain/releases/plain-email@0.15.0) (2026-01-15)

### What's changed

- `EMAIL_HOST_PASSWORD` is now marked as a `Secret` type, ensuring the password is masked when displaying settings in CLI output ([7666190](https://github.com/dropseed/plain/commit/7666190305e13ebd1fc9b536e6415e863c2c0b25))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-email@0.14.0) (2026-01-13)

### What's changed

- Simplified public API exports to only include user-facing classes and functions ([28f4849](https://github.com/dropseed/plain/commit/28f4849ca5692acc1dbef97f1590ddbd2f5afe96))
- Improved README documentation with comprehensive usage examples and installation instructions ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb8a683c65863f4d0b7af9af5b16feec))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-email@0.13.0) (2025-12-04)

### What's changed

- Internal typing improvements for better type checker compatibility ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea05b26dfc7e32c50f2a5a5bc7e098ceb))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-email@0.12.0) (2025-11-12)

### What's changed

- The filebased email backend now requires `EMAIL_FILE_PATH` to be set and raises `ImproperlyConfigured` if not provided ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa929058be517cb1d4ab35bd73a89f26b8))
- `BaseEmailBackend` now uses Python's abstract base class with `@abstractmethod` for better type checking ([245b5f4](https://github.com/dropseed/plain/commit/245b5f472c89178b8b764869f1624f8fc885b0f7))

### Upgrade instructions

- If using the filebased email backend, ensure `EMAIL_FILE_PATH` is configured in your settings or passed when initializing the backend

## [0.11.1](https://github.com/dropseed/plain/releases/plain-email@0.11.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package for improved IDE support and type checking ([5a32120](https://github.com/dropseed/plain/commit/5a3212020c473d3a10763cedd0b0b7ca778911de))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-email@0.11.0) (2025-09-19)

### What's changed

- Updated Python minimum requirement to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307))
- Improved README with installation instructions and table of contents ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))
- Updated package description to "Everything you need to send email in Plain" ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))

### Upgrade instructions

- Update your Python version to 3.13 or higher

## [0.10.2](https://github.com/dropseed/plain/releases/plain-email@0.10.2) (2025-06-23)

### What's changed

- No user-facing changes. Internal documentation and tooling updates only ([82710c3](https://github.com/dropseed/plain/commit/82710c3), [9a1963d](https://github.com/dropseed/plain/commit/9a1963d), [e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3)).

### Upgrade instructions

- No changes required
