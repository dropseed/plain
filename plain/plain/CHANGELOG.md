# plain changelog

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
