# plain-sessions changelog

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
