# plain-sessions changelog

## [0.31.0](https://github.com/dropseed/plain/releases/plain-sessions@0.31.0) (2025-09-30)

### What's changed

- The toolbar integration has been refactored to use the new `ToolbarItem` API instead of `ToolbarPanel`, with `SessionToolbarPanel` renamed to `SessionToolbarItem` ([79654db](https://github.com/dropseed/plain/commit/79654dbefe))

### Upgrade instructions

- No changes required

## [0.30.0](https://github.com/dropseed/plain/releases/plain-sessions@0.30.0) (2025-09-25)

### What's changed

- Preflight checks have been migrated to use the new class-based `PreflightCheck` API with unified `fix` messages instead of separate `msg` and `hint` fields ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461), [c7cde12](https://github.com/dropseed/plain/commit/c7cde12149))
- Preflight check IDs have been renamed to use descriptive names instead of numbered codes (e.g., `security.W010` → `security.session_cookie_not_secure_app`) ([cd96c97](https://github.com/dropseed/plain/commit/cd96c97b25))

### Upgrade instructions

- No changes required

## [0.29.0](https://github.com/dropseed/plain/releases/plain-sessions@0.29.0) (2025-09-12)

### What's changed

- Model manager API has been renamed from `.objects` to `.query` throughout the codebase ([037a239](https://github.com/dropseed/plain/commit/037a239ef4711c4477a211d63c57ad8414096301))

### Upgrade instructions

- Replace any usage of `Session.objects` with `Session.query` in your code (e.g., `Session.objects.filter()` becomes `Session.query.filter()`)

## [0.28.0](https://github.com/dropseed/plain/releases/plain-sessions@0.28.0) (2025-09-09)

### What's changed

- The `SessionStore` now exposes a `model_instance` property that returns the underlying `Session` model instance, making it easier to access session metadata like the ID ([f374290](https://github.com/dropseed/plain/commit/f37429052d7380f3984dd824e285d9029455ada9))
- Session admin interface now displays the numeric session ID instead of session keys for better readability ([b3dca07](https://github.com/dropseed/plain/commit/b3dca0777fc9a409ef84bcfd58daf6a56b7b1c81))
- OpenTelemetry tracing now uses the session ID instead of the session key for better observability ([9cc458e](https://github.com/dropseed/plain/commit/9cc458ef056b783abb1ec20129f1e6dc71eaed23))
- Session toolbar display has been simplified by removing the session key display ([e1fa569](https://github.com/dropseed/plain/commit/e1fa5699edddbc2814e0fad80c9fdf6f6f5e89dc))
- Minimum Python version is now 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb0d5e8f5001efccede4d58d0e26bfea))

### Upgrade instructions

- No changes required

## [0.27.0](https://github.com/dropseed/plain/releases/plain-sessions@0.27.0) (2025-08-27)

### What's changed

- The toolbar panel for sessions has been moved to the new `plain.toolbar` package. A new `SessionToolbarPanel` is now available in `plain.sessions.toolbar` ([e49d54b](https://github.com/dropseed/plain/commit/e49d54bfea162424c73e54bf7ed87e93442af899))
- The README has been significantly expanded with comprehensive documentation including usage examples, configuration options, and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))
- Updated the package description to "Database-backed sessions for managing user state across requests" ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.26.1](https://github.com/dropseed/plain/releases/plain-sessions@0.26.1) (2025-07-23)

### What's changed

- Added bootstrap icons to the Session admin interface with a "person-badge" icon ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2c))

### Upgrade instructions

- No changes required

## [0.26.0](https://github.com/dropseed/plain/releases/plain-sessions@0.26.0) (2025-07-22)

### What's changed

- Session model now uses the new `PrimaryKeyField` instead of `BigAutoField` for the primary key ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef126a15e48b5f85e0652adf841eb7b5c))

### Upgrade instructions

- No changes required

## [0.25.0](https://github.com/dropseed/plain/releases/plain-sessions@0.25.0) (2025-07-18)

### What's changed

- Session middleware now includes OpenTelemetry tracing support, automatically setting the session ID as a span attribute when available ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418da293553fc599ae766eec82f607326))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-sessions@0.24.0) (2025-07-18)

### What's changed

- Migration history was consolidated into a single initial migration file. The new `0001_initial.py` includes all the current schema changes without the intermediate migration steps ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93bfea486529f4806bcd9a9ec5c1217d)).

### Upgrade instructions

- Run `plain migrate --prune plainsessions` to run migrations and delete old ones from the database.

## [0.23.0](https://github.com/dropseed/plain/releases/plain-sessions@0.23.0) (2025-07-07)

### What's changed

- Sessions are now stored in a brand-new `Session` model that uses a numeric primary key, a JSON `session_data` column, and a `created_at` timestamp. A built-in data migration copies existing rows and removes the legacy table ([aec55e3](https://github.com/dropseed/plain/commit/aec55e3)).
- `SessionStore` now subclasses `collections.abc.MutableMapping`, giving it the full standard dictionary interface (iteration, `len()`, `update()`, etc.). Redundant helpers such as `has_key()` were removed ([493d787](https://github.com/dropseed/plain/commit/493d787), [5c1ffd8](https://github.com/dropseed/plain/commit/5c1ffd8)).
- Session persistence was simplified: the cryptographic signing layer was removed and data is now saved as plain JSON via `update_or_create` ([aec55e3](https://github.com/dropseed/plain/commit/aec55e3), [91e6540](https://github.com/dropseed/plain/commit/91e6540)).
- Added admin integration – a `SessionAdmin` viewset is registered so you can view and inspect sessions from Plain Admin under “Sessions” ([aec55e3](https://github.com/dropseed/plain/commit/aec55e3)).
- Additional internal refactors around session caching and attribute names for better readability and performance ([f2beb33](https://github.com/dropseed/plain/commit/f2beb33)).

### Upgrade instructions

- Run your project’s database migrations after upgrading (`plain migrate`). The included migration will automatically convert existing sessions to the new schema.
- Confirm that everything you stash in `request.session` is JSON-serialisable. Complex Python objects that are not JSON-encodable should be converted to primitives (for example, cast to `str`).
- If you were using the deprecated `has_key()` helper, replace it with the standard `in` operator (e.g. `if "foo" in request.session:`).

## [0.22.0](https://github.com/dropseed/plain/releases/plain-sessions@0.22.0) (2025-06-23)

### What's changed

- Added `plain.sessions.test.get_client_session` helper to make it easier to read and mutate the test client’s session inside unit-tests ([eb8a02](https://github.com/dropseed/plain/commit/eb8a023976cac763fbf95e400f8ab96a815a016c)).
- Internal update for the framework’s new single-`DATABASE` configuration. Session persistence no longer relies on `DATABASE_ROUTERS` and always uses the default database connection ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572)).

### Upgrade instructions

- If your project is already using the new single `DATABASE` setting, no action is required.
- Projects that still define `DATABASES` and/or `DATABASE_ROUTERS` in `settings.py` must migrate to the new single `DATABASE` configuration before upgrading.
