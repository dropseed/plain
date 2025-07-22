# plain-models changelog

## [0.39.1](https://github.com/dropseed/plain/releases/plain-models@0.39.1) (2025-07-22)

### What's changed

- Added documentation for sharing fields across models using Python class mixins ([cad3af01d2](https://github.com/dropseed/plain/commit/cad3af01d2))
- Added note about `PrimaryKeyField()` replacement requirement for migrations ([70ea931660](https://github.com/dropseed/plain/commit/70ea931660))

### Upgrade instructions

- No changes required

## [0.39.0](https://github.com/dropseed/plain/releases/plain-models@0.39.0) (2025-07-22)

### What's changed

- Models now use a single automatic `id` field as the primary key, replacing the previous `pk` alias and automatic field system ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Removed the `to_field` option for ForeignKey - foreign keys now always reference the primary key of the related model ([7fc3c88](https://github.com/dropseed/plain/commit/7fc3c88))
- Removed the internal `from_fields` and `to_fields` system used for multi-column foreign keys ([0e9eda3](https://github.com/dropseed/plain/commit/0e9eda3))
- Removed the `parent_link` parameter on ForeignKey and ForeignObject ([6658647](https://github.com/dropseed/plain/commit/6658647))
- Removed `InlineForeignKeyField` from forms ([ede6265](https://github.com/dropseed/plain/commit/ede6265))
- Merged ForeignObject functionality into ForeignKey, simplifying the foreign key implementation ([e6d9aaa](https://github.com/dropseed/plain/commit/e6d9aaa))
- Cleaned up unused code in ForeignKey and fixed ForeignObjectRel imports ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6))

### Upgrade instructions

- Replace any direct references to `pk` with `id` in your models and queries (e.g., `user.pk` becomes `user.id`)
- Remove any `to_field` arguments from ForeignKey definitions - they are no longer supported
- Remove any `parent_link=True` arguments from ForeignKey definitions - they are no longer supported
- Replace any usage of `InlineForeignKeyField` in forms with standard form fields
- `models.BigAutoField(auto_created=True, primary_key=True)` need to be replaced with `models.PrimaryKeyField()` in migrations

## [0.38.0](https://github.com/dropseed/plain/releases/plain-models@0.38.0) (2025-07-21)

### What's changed

- Added `get_or_none()` method to QuerySet which returns a single object matching the given arguments or None if no object is found ([48e07bf](https://github.com/dropseed/plain/commit/48e07bf))

### Upgrade instructions

- No changes required

## [0.37.0](https://github.com/dropseed/plain/releases/plain-models@0.37.0) (2025-07-18)

### What's changed

- Added OpenTelemetry instrumentation for database operations - all SQL queries now automatically generate OpenTelemetry spans with standardized attributes following semantic conventions ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0))
- Database operations in tests are now wrapped with tracing suppression to avoid generating telemetry noise during test execution ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0))

### Upgrade instructions

- No changes required

## [0.36.0](https://github.com/dropseed/plain/releases/plain-models@0.36.0) (2025-07-18)

### What's changed

- Removed the `--merge` option from the `makemigrations` command ([d366663](https://github.com/dropseed/plain/commit/d366663))
- Improved error handling in the `restore-backup` command using Click's error system ([88f06c5](https://github.com/dropseed/plain/commit/88f06c5))

### Upgrade instructions

- No changes required

## [0.35.0](https://github.com/dropseed/plain/releases/plain-models@0.35.0) (2025-07-07)

### What's changed

- Added the `plain models list` CLI command which prints a nicely formatted list of all installed models, including their table name, fields, and originating package. You can pass package labels to filter the output or use the `--app-only` flag to only show first-party app models ([1bc40ce](https://github.com/dropseed/plain/commit/1bc40ce)).
- The MySQL backend no longer enforces a strict `mysqlclient >= 1.4.3` version check and had several unused constraint-handling methods removed, reducing boilerplate and improving compatibility with a wider range of `mysqlclient` versions ([6322400](https://github.com/dropseed/plain/commit/6322400), [67f21f6](https://github.com/dropseed/plain/commit/67f21f6)).

### Upgrade instructions

- No changes required

## [0.34.4](https://github.com/dropseed/plain/releases/plain-models@0.34.4) (2025-07-02)

### What's changed

- The built-in `on_delete` behaviors (`CASCADE`, `PROTECT`, `RESTRICT`, `SET_NULL`, `SET_DEFAULT`, and the callables returned by `SET(...)`) no longer receive the legacy `using` argument. Their signatures are now `(collector, field, sub_objs)` ([20325a1](https://github.com/dropseed/plain/commit/20325a1)).
- Removed the unused `interprets_empty_strings_as_nulls` backend feature flag and the related fallback logic ([285378c](https://github.com/dropseed/plain/commit/285378c)).

### Upgrade instructions

- No changes required

## [0.34.3](https://github.com/dropseed/plain/releases/plain-models@0.34.3) (2025-06-29)

### What's changed

- Simplified log output when creating or destroying test databases during test setup. The messages now display the test database name directly and no longer reference the deprecated "alias" terminology ([a543706](https://github.com/dropseed/plain/commit/a543706)).

### Upgrade instructions

- No changes required

## [0.34.2](https://github.com/dropseed/plain/releases/plain-models@0.34.2) (2025-06-27)

### What's changed

- Fixed PostgreSQL `_nodb_cursor` fallback that could raise `TypeError: __init__() got an unexpected keyword argument 'alias'` when the maintenance database wasn't available ([3e49683](https://github.com/dropseed/plain/commit/3e49683)).
- Restored support for the `USING` clause when creating PostgreSQL indexes; custom index types such as `GIN` and `GIST` are now generated correctly again ([9d2b8fe](https://github.com/dropseed/plain/commit/9d2b8fe)).

### Upgrade instructions

- No changes required

## [0.34.1](https://github.com/dropseed/plain/releases/plain-models@0.34.1) (2025-06-23)

### What's changed

- Fixed Markdown bullet indentation in the 0.34.0 release notes so they render correctly ([2fc81de](https://github.com/dropseed/plain/commit/2fc81de)).

### Upgrade instructions

- No changes required

## [0.34.0](https://github.com/dropseed/plain/releases/plain-models@0.34.0) (2025-06-23)

### What's changed

- Switched to a single `DATABASE` setting instead of `DATABASES` and removed `DATABASE_ROUTERS`. A helper still automatically populates `DATABASE` from `DATABASE_URL` just like before ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).
- The `plain.models.db` module now exposes a `db_connection` object that lazily represents the active database connection. Previous `connections`, `router`, and `DEFAULT_DB_ALIAS` exports were removed ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- Replace any `DATABASES` definition in your settings with a single `DATABASE` dict (keys are identical to the inner dict you were previously using).
- Remove any `DATABASE_ROUTERS` configuration – multiple databases are no longer supported.
- Update import sites:
    - `from plain.models import connections` → `from plain.models import db_connection`
    - `from plain.models import router` → (no longer needed; remove usage or switch to `db_connection` where appropriate)
    - `from plain.models.connections import DEFAULT_DB_ALIAS` → (constant removed; default database is implicit)
