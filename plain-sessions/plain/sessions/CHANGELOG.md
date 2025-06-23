# plain-sessions changelog

## [0.22.0](https://github.com/dropseed/plain/releases/plain-sessions@0.22.0) (2025-06-23)

### What's changed

- Added `plain.sessions.test.get_client_session` helper to make it easier to read and mutate the test client’s session inside unit-tests ([eb8a02](https://github.com/dropseed/plain/commit/eb8a023976cac763fbf95e400f8ab96a815a016c)).
- Internal update for the framework’s new single-`DATABASE` configuration. Session persistence no longer relies on `DATABASE_ROUTERS` and always uses the default database connection ([d346d81](https://github.com/dropseed/plain/commit/d346d81567d2cc45bbed93caba18a195de10c572)).

### Upgrade instructions

- If your project is already using the new single `DATABASE` setting, no action is required.
- Projects that still define `DATABASES` and/or `DATABASE_ROUTERS` in `settings.py` must migrate to the new single `DATABASE` configuration before upgrading.
