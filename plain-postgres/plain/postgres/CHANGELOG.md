# plain-postgres changelog

## [0.101.0](https://github.com/dropseed/plain/releases/plain-postgres@0.101.0) (2026-04-30)

### What's changed

- **Validate CHECK constraints in the same converge run that adds them.** `AddConstraintFix` now runs `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID` followed by `ALTER TABLE ... VALIDATE CONSTRAINT` in a single `apply()`. The add is catalog-only (brief lock) and validate uses `SHARE UPDATE EXCLUSIVE` (doesn't block writes), so there's no benefit to deferring validation to a later run. Existing rows are checked before convergence reports success — previously, a CHECK constraint could be added in `NOT VALID` state and the validation step was its own follow-up fix. ([dc7eb8d3c2b7](https://github.com/dropseed/plain/commit/dc7eb8d3c2b7))
- `plain-postgres` rule references updated for the simpler `plain docs` CLI (no more `--section`). ([e03c3bd8b6d3](https://github.com/dropseed/plain/commit/e03c3bd8b6d3))

### Upgrade instructions

- No changes required. The next `plain postgres sync` (or scheduled converge run) on a database with pending CHECK constraints will now both add and validate them in one step instead of two.

## [0.100.0](https://github.com/dropseed/plain/releases/plain-postgres@0.100.0) (2026-04-28)

### What's changed

- **Replaced the `violation_error_message` / `violation_error_code` triad on `CheckConstraint` and `UniqueConstraint` with a single `violation_error` kwarg.** The new kwarg accepts anything `ValidationError(...)` accepts — a string, a `{field: message}` dict, a list, or a fully-formed `ValidationError` — so message text, error code, and field routing all live on one object. ([8650edc22c09](https://github.com/dropseed/plain/commit/8650edc22c09))
- **Single-field `UniqueConstraint` now auto-routes flat errors to its field.** A `violation_error="That email is taken."` on `UniqueConstraint(fields=["email"])` lands on the `email` form field instead of `NON_FIELD_ERRORS`. A caller-built `ValidationError({"other_field": ...})` is preserved as-is. ([8650edc22c09](https://github.com/dropseed/plain/commit/8650edc22c09))
- **Dropped the hardcoded `code == "unique"` routing in `validate_constraints()`.** Routing is now uniform across constraint types: dict-form errors land on fields, flat errors go to `NON_FIELD_ERRORS`. ([8650edc22c09](https://github.com/dropseed/plain/commit/8650edc22c09))
- **Removed the `%(name)s` interpolation magic** on `BaseConstraint.default_violation_error_message`. The default message still includes the constraint name; users wanting runtime interpolation can pass `ValidationError(..., params={"name": ...})`. ([8650edc22c09](https://github.com/dropseed/plain/commit/8650edc22c09))
- Documented that `save()` runs `full_clean()` by default (`clean_and_validate=True`); fixed the README's Validation example which previously implied users had to override `save()` to call `full_clean()` manually. ([8650edc22c09](https://github.com/dropseed/plain/commit/8650edc22c09))

### Upgrade instructions

- Replace `violation_error_message="..."` and `violation_error_code="..."` on `CheckConstraint` / `UniqueConstraint` with a single `violation_error=ValidationError("...", code="...")` (or a string if you only need the message).
- If you relied on the implicit single-field-unique routing for a constraint with a custom `violation_error_code`, no change needed — single-field `UniqueConstraint` still auto-routes by default.
- If you used `%(name)s` in `violation_error_message`, switch to `ValidationError("...", params={"name": "your_constraint_name"})` or hardcode the name.

## [0.99.1](https://github.com/dropseed/plain/releases/plain-postgres@0.99.1) (2026-04-26)

### What's changed

- **Duplicate-index check now catches expression-prefix duplicates.** Previously the check excluded any index containing expressions (it compared raw `indkey`/`indclass` arrays), so a redundant `(LOWER(email))` alongside `(LOWER(email), team_id)` was missed. The query now compares per-column `pg_get_indexdef(indexrelid, k, false)` text — canonical output that includes column name/expression, opclass, collation, and sort order — and checks `pg_am.amname` separately so a hash and btree on the same column don't false-match. ([4bd8a713649f](https://github.com/dropseed/plain/commit/4bd8a713649f))

### Upgrade instructions

- No changes required.

## [0.99.0](https://github.com/dropseed/plain/releases/plain-postgres@0.99.0) (2026-04-23)

### What's changed

- **Reworked `plain postgres diagnose` around tiered findings.** Warnings are now reserved for things the user can fix by editing model code or taking an app-level action — every warning carries a copy-paste fix or a model-file pointer (`app/path.py :: ModelName`). Noisy one-off signals (cache/index hit ratios, XID wraparound, connection saturation, pg_stat_statements availability, stats reset age) render as **informational context**; DB-state facts whose remedies live outside Plain (stats freshness, vacuum health, index bloat) render as **operational context** instead of warnings. Added `--verbose` to expand every check, and `--all` still includes installed-package tables. ([26abb6cbc075](https://github.com/dropseed/plain/commit/26abb6cbc075))
- **New diagnostic checks:** `stats_freshness` (uses `pg_class.reltuples` so it survives `pg_stat_reset`), `index_bloat` (ioguix btree estimator, public schema only), `missing_index_candidates` (seq-scan heuristics with per-query drill-down from `pg_stat_statements`), `blocking_queries` (wait age from `pg_locks.waitstart`, PG 14+), and `long_running_connections` (xact age for idle-in-transaction). Findings include **cross-check caveats** — e.g. an `unused_indexes` finding on a table that's also flagged by `stats_freshness` or `vacuum_health` now carries a warning that dropping the index may be premature. ([26abb6cbc075](https://github.com/dropseed/plain/commit/26abb6cbc075))
- **Permission-safe probes.** Checks that may hit permission errors (`pg_stat_statements`, `pg_stat_activity`, `pg_locks`) now wrap their queries in `cursor.connection.transaction()` so a failure rolls back cleanly in either autocommit or transaction mode without cascade-failing later checks. ([26abb6cbc075](https://github.com/dropseed/plain/commit/26abb6cbc075))
- **Refactored internals.** The 1800+ line `introspection/health.py` split into an `introspection/health/` package along natural seams (types, ownership, context, helpers, checks grouped by `structural`/`cumulative`/`snapshot`, and a runner). Public re-exports are unchanged. ([26abb6cbc075](https://github.com/dropseed/plain/commit/26abb6cbc075))
- Adapter annotations use `Response` after plain 0.135.0 merged `ResponseBase` into `Response`. ([f5007281d7fa](https://github.com/dropseed/plain/commit/f5007281d7fa))

### Upgrade instructions

- Requires `plain>=0.135.0`.
- No code changes required. If you parse `plain postgres diagnose --json`, note the new `tier` field on each finding (`"structural"`, `"cumulative"`, `"snapshot"`, or `"operational"`) — operational findings still carry `status: "warning"` but the CLI renders them as context rather than as alarming warnings.

## [0.98.0](https://github.com/dropseed/plain/releases/plain-postgres@0.98.0) (2026-04-22)

### What's changed

- **Pool-backed connections via `psycopg_pool.ConnectionPool`.** A new `sources` abstraction routes `DatabaseConnection` through either a long-lived `PoolSource` (runtime) or a `DirectSource` (management / one-shot). Each request checks a connection out of the pool on first use and returns it when the HTTP request finishes. `psycopg>=3.2` and `psycopg-pool>=3.2` are now declared as hard dependencies. ([2a51b25](https://github.com/dropseed/plain/commit/2a51b25))
- **New `DatabaseConnectionMiddleware` (required).** Add `"plain.postgres.DatabaseConnectionMiddleware"` to `MIDDLEWARE` — it's what returns the pooled connection at the end of each request. For `StreamingResponse` / `AsyncStreamingResponse` the connection is returned after the body fully drains, so generators that lazily query the database (e.g. `Model.query.iterator()`) keep their cursor alive until the last chunk is sent. A new `postgres.middleware_installed` preflight check errors if the middleware is missing. ([2a51b25](https://github.com/dropseed/plain/commit/2a51b25))
- **Connection settings replaced with pool settings.** `POSTGRES_CONN_MAX_AGE` and `POSTGRES_CONN_HEALTH_CHECKS` are gone. Tune the pool with `POSTGRES_POOL_MIN_SIZE` (default `4`), `POSTGRES_POOL_MAX_SIZE` (default `20`), `POSTGRES_POOL_MAX_LIFETIME` seconds (default `3600.0`), and `POSTGRES_POOL_TIMEOUT` seconds (default `30.0`). Each is also available as a `PLAIN_POSTGRES_POOL_*` environment variable. ([2a51b25](https://github.com/dropseed/plain/commit/2a51b25))
- **`plain.postgres.connections` module removed.** `get_connection`, `has_connection`, `use_management_connection`, and `read_only` now live in `plain.postgres.db` (the underscore-less counterpart). ([2a51b25](https://github.com/dropseed/plain/commit/2a51b25))
- **`read_only()` is now pgbouncer-safe.** It opens a single `BEGIN READ ONLY` transaction for the block (previously a session-level `SET default_transaction_read_only = on`). Nested `atomic()` blocks become savepoints of the outer read-only transaction. Entering `read_only()` inside an existing `atomic()` block now raises `TransactionManagementError`. The old `DatabaseConnection.set_read_only()` method is removed. ([ebdec30](https://github.com/dropseed/plain/commit/ebdec30))
- **Added OTel pool + rowcount metrics and semconv polish.** Wires the `db.client.connection.*` metric family (count, max, idle.min/max, pending_requests, wait_time, use_time, timeouts) from the pool's stats and the acquire/release path, plus `db.client.response.returned_rows` for SELECT queries including streamed iterators. Query spans now carry `server.address` / `server.port` alongside `network.peer.*`, and the tracer/meter are tagged with the `plain.postgres` package version for `InstrumentationScope`. ([61278d5](https://github.com/dropseed/plain/commit/61278d5))
- **Moved `psql` CLI orchestration off `DatabaseConnection`.** New `postgres_cli_args` / `postgres_cli_env` helpers in `plain.postgres.database_url` build the arguments and environment for `psql`, `pg_dump`, etc.; `plain postgres shell` and the `plain-dev` backup client both use them. `DatabaseConnection.runshell()` and `executable_name` are gone. ([5b4a488](https://github.com/dropseed/plain/commit/5b4a488))
- **Removed dead connection-lifecycle plumbing.** `close_if_unusable_or_obsolete`, `close_if_health_check_failed`, `closed_in_transaction`, `is_usable`, `health_check_enabled`, `health_check_done`, `close_at`, `_maintenance_cursor`, and `DatabaseConnection.from_url` are gone — the pool handles recycling, health checks, and URL parsing. `close()` now validates there's no open atomic block instead of silently deferring. ([044e942](https://github.com/dropseed/plain/commit/044e942), [2a51b25](https://github.com/dropseed/plain/commit/2a51b25))
- **Inlined `pg_version` and removed `temporary_connection()`.** The single caller now reads `connection.info.server_version` directly; `temporary_connection()` has no remaining users. ([319f6ac](https://github.com/dropseed/plain/commit/319f6ac))
- **`APIResult` shorthand returns moved out of `View`.** Any internal views that relied on dict/int shorthand now wrap their returns in `JsonResponse` / `Response(status_code=...)` to match plain 0.134.0's narrower `View` handler return type. ([1935f3f](https://github.com/dropseed/plain/commit/1935f3f))
- **Adapter registration extracted to `plain.postgres.adapters`.** `PlainRangeDumper` and `get_adapters_template()` moved out of `connection.py` into their own module.

### Upgrade instructions

- Requires `plain>=0.134.0`.
- **Add the middleware** to `app/settings.py`:

    ```python
    MIDDLEWARE = [
        "plain.postgres.DatabaseConnectionMiddleware",
        # ...the rest of your middleware
    ]
    ```

    Place it near the top so downstream middleware can use the database inside `before_request` / `after_response` and still have the connection returned cleanly. Preflight will error if it's missing.

- **Replace `POSTGRES_CONN_MAX_AGE` / `POSTGRES_CONN_HEALTH_CHECKS`** with the pool settings (`POSTGRES_POOL_MIN_SIZE`, `POSTGRES_POOL_MAX_SIZE`, `POSTGRES_POOL_MAX_LIFETIME`, `POSTGRES_POOL_TIMEOUT`) or remove them to take the defaults.

- **Update imports from `plain.postgres.connections`** to `plain.postgres.db`:

    ```python
    # Before
    from plain.postgres.connections import get_connection, read_only, use_management_connection

    # After
    from plain.postgres.db import get_connection, read_only, use_management_connection
    ```

- **If you called `DatabaseConnection.set_read_only(True)`** for a sticky read-only session, switch to the `read_only()` context manager around the block you want read-only. If you need session-level enforcement outside a transaction, open a `DirectSource` connection yourself and issue `SET default_transaction_read_only = on` on it.

- **If you entered `read_only()` inside an `atomic()` block**, move `read_only()` to the outer position — it now owns the transaction. Nested `atomic()` blocks inside `read_only()` are fine (they become savepoints).

- **If you pinned `psycopg` via your own dependency**, make sure it's `>=3.2`, and add `psycopg-pool>=3.2` if you were installing psycopg without extras.

## [0.97.0](https://github.com/dropseed/plain/releases/plain-postgres@0.97.0) (2026-04-21)

### What's changed

- **Replaced individual `POSTGRES_*` connection fields with a single `POSTGRES_URL` setting.** `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DATABASE`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_OPTIONS`, and `POSTGRES_TIME_ZONE` are gone — configure the connection with one URL (e.g. `postgresql://user:pass@host:5432/db?sslmode=require`). `DATABASE_URL` is still read as a fallback. Set the URL to `none` to explicitly disable the database (e.g. during Docker image builds). ([770a74606463](https://github.com/dropseed/plain/commit/770a74606463))
- **Added `POSTGRES_MANAGEMENT_URL` for routing DDL through a separate connection.** When set, `plain migrations create|apply|list|prune|squash`, `plain postgres sync|converge|schema|diagnose|drop-unknown-tables|shell` connect through this URL instead of `POSTGRES_URL`. Use it to bypass transaction-mode poolers (PlanetScale, Supabase's pooler, Neon's pooler, pgbouncer) for schema changes, long transactions, and `pg_dump`. A new `use_management_connection()` context manager routes custom code through the same connection. When unset, all commands use `POSTGRES_URL` — no behavior change for existing apps. ([d1cc9630d049](https://github.com/dropseed/plain/commit/d1cc9630d049))
- **Extracted the test-database lifecycle off `DatabaseConnection`.** Test setup/teardown now lives in `plain.postgres.test` instead of coupling it to the runtime connection class. ([ea67f82c746c](https://github.com/dropseed/plain/commit/ea67f82c746c))
- **Removed thin psycopg re-export wrappers.** Internal code now imports directly from `psycopg` rather than the redundant Plain-level passthroughs. ([d1cb74100e0d](https://github.com/dropseed/plain/commit/d1cb74100e0d))

### Upgrade instructions

- **Replace individual `POSTGRES_*` settings with `POSTGRES_URL`** in `app/settings.py` (or `PLAIN_POSTGRES_URL` in the environment). For example:

    ```python
    # Before
    POSTGRES_HOST = "localhost"
    POSTGRES_PORT = 5432
    POSTGRES_DATABASE = "myapp"
    POSTGRES_USER = "app"
    POSTGRES_PASSWORD = "secret"

    # After
    POSTGRES_URL = "postgresql://app:secret@localhost:5432/myapp"
    ```

    Apps that already set `DATABASE_URL` in the environment don't need any change.

- **If `POSTGRES_OPTIONS` or `POSTGRES_TIME_ZONE` were set**, move them into the URL as query parameters (e.g. `?application_name=web&timezone=UTC`).
- **If you run behind a transaction-mode pooler**, consider setting `POSTGRES_MANAGEMENT_URL` to a direct-to-Postgres connection string so `plain migrations` and `plain postgres sync` can issue DDL.

## [0.96.0](https://github.com/dropseed/plain/releases/plain-postgres@0.96.0) (2026-04-17)

### What's changed

- **`DateTimeField` gained `create_now=True` / `update_now=True` kwargs; `auto_now_add` and `auto_now` are removed.** `create_now=True` installs a persistent `DEFAULT STATEMENT_TIMESTAMP()` column default — raw-SQL inserts now get a value, not just ORM-driven ones. `update_now=True` stamps the column on every `save()` via `pre_save`. Preflight requires `update_now=True` to be paired with `create_now=True` or `allow_null=True` so existing rows have a backfill path. `default=` is no longer accepted on `DateTimeField`. ([5d145e4](https://github.com/dropseed/plain/commit/5d145e4), [a44e5ec](https://github.com/dropseed/plain/commit/a44e5ec), [091bac7](https://github.com/dropseed/plain/commit/091bac7))
- **`UUIDField` gained `generate=True`; `default=GenRandomUUID()` is no longer accepted.** `generate=True` installs `DEFAULT gen_random_uuid()` on the column, so Postgres produces a fresh UUID per row (raw-SQL inserts included). ([a44e5ec](https://github.com/dropseed/plain/commit/a44e5ec))
- **Added `RandomStringField(length=N)`** for per-row DB-generated random hex strings. Backed by a `DEFAULT` that slices `gen_random_uuid()::text`; use in place of Python `default=secrets.token_hex` callables for tokens, slugs, and short IDs. Alphabet is always hex — an earlier draft accepted `alphabet=` but it was dropped because the generated expression grew to ~4 KB for a 40-char token. ([34858ab](https://github.com/dropseed/plain/commit/34858ab), [0918702](https://github.com/dropseed/plain/commit/0918702))
- **Added `GenRandomUUID()` function.** Exported at `plain.postgres.functions.GenRandomUUID`. No longer valid as `default=`; use `UUIDField(generate=True)` or reference it in annotations/expressions. ([da58230](https://github.com/dropseed/plain/commit/da58230))
- **Callable `default=` is banned on model fields.** `default=uuid.uuid4`, `default=secrets.token_hex`, `default=dict`, `default=lambda: ...`, etc. raise `TypeError` at field construction. Use DB-side generation (`UUIDField(generate=True)`, `RandomStringField`, `DateTimeField(create_now=True)`) or a static literal. Empty-collection defaults use literal `{}` / `[]` — the value is deep-copied on each `get_default()` call. ([091bac7](https://github.com/dropseed/plain/commit/091bac7))
- **Literal `default=X` values now persist as column `DEFAULT` in the catalog and are reconciled by convergence.** Previously `default=` was Python-side only; now it is compiled to a DDL `DEFAULT <literal>` clause. Raw-SQL `INSERT`s get the default, and drift is detected if someone edits it out-of-band. ([c59473d](https://github.com/dropseed/plain/commit/c59473d), [6ed95fe](https://github.com/dropseed/plain/commit/6ed95fe), [161c7f9](https://github.com/dropseed/plain/commit/161c7f9))
- **Column nullability and DEFAULT transitions now go through convergence, not the schema editor.** `AlterField` is a no-op when only `allow_null` or `default=` changed; `plain postgres sync` applies the change with online-safe DDL (`CHECK NOT VALID` + `VALIDATE` + `SET NOT NULL` for NOT NULL flips; catalog-only `SET`/`DROP DEFAULT` for default changes). The old 4-way NULL → NOT NULL backfill in the schema editor is gone — if a column has NULL rows, convergence now blocks with guidance instead of silently backfilling. ([3e10ab2](https://github.com/dropseed/plain/commit/3e10ab2), [c59473d](https://github.com/dropseed/plain/commit/c59473d))
- **Every framework-issued DDL statement now emits `SET LOCAL lock_timeout` and, where relevant, `SET LOCAL statement_timeout`.** Defaults are `3s` each and apply to both migration operations and convergence fixes. Non-blocking operations (`CREATE INDEX CONCURRENTLY`, `VALIDATE CONSTRAINT`) skip `statement_timeout`. Configure via new settings `POSTGRES_MIGRATION_LOCK_TIMEOUT`, `POSTGRES_MIGRATION_STATEMENT_TIMEOUT`, `POSTGRES_CONVERGENCE_LOCK_TIMEOUT`, `POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT` (all `PLAIN_POSTGRES_*` env-var compatible). `RunSQL(no_timeout=True)` opts a single operation out — useful for batched backfills that manage their own timeouts. ([11d903b](https://github.com/dropseed/plain/commit/11d903b))
- **The autodetector rejects unsafe column type changes.** Base-type changes outside a lossless widening allowlist (`smallint → integer`, `smallint → bigint`, `integer → bigint`) raise `MigrationSchemaError` with scaffold guidance instead of emitting an `AlterField` that would compile to a blind `ALTER COLUMN ... TYPE ... USING col::newtype`. Parameter-only changes (e.g. `max_length`) and the widening allowlist still auto-generate. ([073a9af](https://github.com/dropseed/plain/commit/073a9af))
- **The autodetector rejects adding a NOT NULL column without a default.** Previously Plain prompted interactively for a one-shot value; now the autodetector errors out with two remediation options: declare a `default=`, or add the field as nullable, backfill, and drop `allow_null=True` via convergence. The `MigrationQuestioner.ask_not_null_*` prompts are gone. ([091bac7](https://github.com/dropseed/plain/commit/091bac7))
- **`AddField` / `AlterField` no longer accept `preserve_default`.** The argument is removed from both operation classes and from `ProjectState.add_field` / `alter_field`. Existing migration files that pass it will fail to load — regenerate them or remove the kwarg. ([c0a117f](https://github.com/dropseed/plain/commit/c0a117f))
- **Backslashes are banned in string `default=` values.** `default=r"C:\path"` raises `ValueError` at construction to prevent spurious DEFAULT drift on every convergence run. ([f8b6227](https://github.com/dropseed/plain/commit/f8b6227))
- **`choices=` is now only accepted on `TextField` (and `TimeZoneField`).** Other fields (`IntegerField`, `BooleanField`, etc.) reject `choices=` at call time. ([01584dc](https://github.com/dropseed/plain/commit/01584dc))
- **Removed `IntegerChoices` and the `Choices` base class.** Only `TextChoices` remains; it now subclasses `str, enum.Enum` directly. ([96acf13](https://github.com/dropseed/plain/commit/96acf13))
- **`max_length=` is now only accepted on `TextField`, `BinaryField`, and `EncryptedTextField`.** Other fields reject it. ([aaa0fb6](https://github.com/dropseed/plain/commit/aaa0fb6))
- **`default=` is no longer accepted on `ForeignKeyField`, `ManyToManyField`, `BinaryField`, `EncryptedTextField`, or `EncryptedJSONField`.** ([60299dc](https://github.com/dropseed/plain/commit/60299dc), [99ba5c2](https://github.com/dropseed/plain/commit/99ba5c2))
- **`ManyToManyField` signature is now explicit** — it rejects `required=`, `allow_null=`, `default=`, and `validators=` with `TypeError`. ([be7fd86](https://github.com/dropseed/plain/commit/be7fd86))
- **Removed `error_messages=` from model fields and `ModelForm.Meta`.** Form-field `error_messages` is unchanged; this only affects the model layer. ([4dee5ec](https://github.com/dropseed/plain/commit/4dee5ec))
- **`PrimaryKeyField` takes no arguments.** It is always `bigint GENERATED BY DEFAULT AS IDENTITY NOT NULL`. Removed kwargs for `required`, `allow_null`, `default`, and `validators`; the type stub now matches the runtime signature. ([ca122c9](https://github.com/dropseed/plain/commit/ca122c9), [0ecd71e](https://github.com/dropseed/plain/commit/0ecd71e))
- **`plain postgres sync --check` now prints pending work.** Previously `--check` only exited non-zero; it now enumerates pending migrations, convergence items, and blocked items with guidance. ([0de289d](https://github.com/dropseed/plain/commit/0de289d))
- **Fixed index drift false positive for `DESC` / `NULLS FIRST|LAST` columns.** Indexes like `Index(fields=["-created_at"])` were rebuilt on every `postgres sync` because the introspection parser misread the sort direction as an opclass. ([07cb500](https://github.com/dropseed/plain/commit/07cb500))
- **Fixed `Field.deconstruct()` over-shortening import paths** — `plain.postgres.fields.<submod>.X` now shortens to `plain.postgres.X` only when `X` is actually re-exported at the top level. ([34858ab](https://github.com/dropseed/plain/commit/34858ab))
- **`ModelForm` no longer marks DB-expression-default and auto-filled fields as `required`.** Fields with `db_returning=True` (e.g. `create_now=True`, `generate=True`, `RandomStringField`) and `auto_fills_on_save=True` (`update_now=True`) produce form fields with `required=False` and preserve the `DATABASE_DEFAULT` sentinel through `construct_instance` so INSERT emits `DEFAULT` instead of NULL on empty submissions. `modelfield_to_formfield` now returns `None` for non-column-backed fields (M2M, etc.). ([6ed95fe](https://github.com/dropseed/plain/commit/6ed95fe))
- **Internal restructuring.** `Field` is split into `ColumnField` → `DefaultableField` → `ChoicesField` with kwargs scoped to the fields that actually accept them. `plain.postgres.fields.__init__` is split into per-type modules (`base`, `text`, `numeric`, `temporal`, `boolean`, `binary`, `uuid`, `network`, `duration`, `primary_key`). `PrimaryKeyField` moved off the `BigIntegerField → IntegerField` chain onto `ColumnField[int]` directly. `non_db_attrs` renamed to `non_migration_attrs`. Removed dead Django-era internals: `SubqueryConstraint`, `MultiColSource`, multi-column FK machinery, multi-table-inheritance UPDATE machinery, `Field.description`, `Field.value_to_string()`, `Field.get_limit_choices_to()`. ([476e1ae](https://github.com/dropseed/plain/commit/476e1ae), [9ed8cc6](https://github.com/dropseed/plain/commit/9ed8cc6), [ca122c9](https://github.com/dropseed/plain/commit/ca122c9), [21cf85f](https://github.com/dropseed/plain/commit/21cf85f), [18080ca](https://github.com/dropseed/plain/commit/18080ca), [9d4ff49](https://github.com/dropseed/plain/commit/9d4ff49), [07b5f0b](https://github.com/dropseed/plain/commit/07b5f0b), [176f56e](https://github.com/dropseed/plain/commit/176f56e), [16e4fcd](https://github.com/dropseed/plain/commit/16e4fcd), [cb98bfa](https://github.com/dropseed/plain/commit/cb98bfa))

### Upgrade instructions

- **Replace `auto_now_add=True` with `create_now=True`** on every `DateTimeField`.
- **Replace `auto_now=True` with `update_now=True`**. If the field was `NOT NULL`, also set `create_now=True` (or `allow_null=True`) — preflight will fail otherwise.
- **Replace `DateTimeField(default=timezone.now)` / `default=Now()`** with `DateTimeField(create_now=True)`. `DateTimeField(default=...)` is no longer accepted.
- **Replace `UUIDField(default=uuid.uuid4)` and `UUIDField(default=GenRandomUUID())`** with `UUIDField(generate=True)`. `UUIDField(default=...)` is no longer accepted.
- **Replace `default=secrets.token_hex` / `default=secrets.token_urlsafe`** with `RandomStringField(length=N)` (hex output only).
- **Replace `default=dict` / `default=list`** with `default={}` / `default=[]`. Any other callable passed as `default=` will now raise `TypeError`.
- **Remove `choices=` from non-text fields** (`IntegerField`, `BooleanField`, etc.).
- **Replace `IntegerChoices` usages** with `TextChoices` or a plain `enum.IntEnum`. `Choices` (the base class) is also gone.
- **Remove `max_length=` from any field that isn't `TextField`, `BinaryField`, or `EncryptedTextField`.**
- **Remove `default=` from `ForeignKeyField`, `BinaryField`, `EncryptedTextField`, and `EncryptedJSONField`.**
- **Remove `required=`, `allow_null=`, `default=`, and `validators=` from `ManyToManyField`** — its signature is now explicit (`to`, `through`, `through_fields`, `related_query_name`, `limit_choices_to`, `symmetrical`).
- **Remove kwargs from `PrimaryKeyField()`** — it no longer accepts any.
- **Remove `error_messages=` from model-level fields and `ModelForm.Meta`.** (Form-field `error_messages` on standalone form fields is unchanged.)
- **Escape backslashes in string `default=` values.** `default="C:\\path"` is fine; `default=r"C:\path"` now raises at construction.
- **Edit or regenerate migration files that pass `preserve_default=...`** to `AddField` / `AlterField` — the kwarg was removed.
- **Rename `non_db_attrs` to `non_migration_attrs`** in any custom field subclass.
- **If your migrations hit the new 3s `statement_timeout`** against a large dev/staging DB, raise it for that run via `PLAIN_POSTGRES_MIGRATION_STATEMENT_TIMEOUT=30s`, or pass `RunSQL(sql, no_timeout=True)` on individual long-running operations.
- **Run `plain postgres sync`** after upgrading to let convergence install persisted column DEFAULTs on existing tables.

## [0.95.0](https://github.com/dropseed/plain/releases/plain-postgres@0.95.0) (2026-04-14)

### What's changed

- **Deletes now run as a single DELETE statement and cascade through Postgres `ON DELETE` clauses.** The Python `Collector` (which walked relationships in Python to fire per-table DELETEs) has been removed. `Model.delete()` and `QuerySet.delete()` issue one statement and let Postgres do the cascading via the FK actions installed by convergence. The old Collector path required N queries per cascade; the new path requires exactly one. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **`Model.delete()` and `QuerySet.delete()` now return `int`** (the directly-deleted row count). They previously returned a `(count, {label: count})` tuple — Postgres does not report cascaded counts, and the per-label dict was Collector-only bookkeeping. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **`on_delete` constants are now `OnDelete` instances, not bare functions.** `ForeignKeyField` rejects any non-`OnDelete` value at construction, and the declared action is emitted as the FK's Postgres `ON DELETE` clause. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **Removed `PROTECT`, `SET()`, `SET_DEFAULT`, `ProtectedError`, and `RestrictedError`.** `PROTECT` and `SET(callable)` had no Postgres equivalent (prefer `RESTRICT`). `SET_DEFAULT` was removed because Plain does not currently persist Python model defaults as DB-level column defaults — emitting `ON DELETE SET DEFAULT` would set children to `NULL` on bypass-the-ORM deletes, contradicting the model's intent. `SET_DEFAULT` will return once DB-level defaults are supported. `RESTRICT` now surfaces as `psycopg.errors.IntegrityError` directly. ([670dab428ad2](https://github.com/dropseed/plain/commit/670dab428ad2), [29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **Renamed `DO_NOTHING` to `NO_ACTION`** to match Postgres's SQL term. No behavior change. ([5fcf8aa9ced3](https://github.com/dropseed/plain/commit/5fcf8aa9ced3))
- **Convergence now owns FK `on_delete` drift.** `plain postgres sync` introspects `pg_constraint.confdeltype`, compares it to the declared `on_delete`, and replaces the constraint when they drift. Replacement uses `ADD CONSTRAINT … NOT VALID` + `VALIDATE` to minimize lock time. Existing databases auto-upgrade on their next sync. ([211840197e1e](https://github.com/dropseed/plain/commit/211840197e1e))
- **Preflight rejects `db_constraint=False` with a non-`NO_ACTION` `on_delete`.** Without a constraint there is no place to attach a deletion action. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **Tightened types.** `on_delete` is now typed as `OnDelete` everywhere (was `Any`). `ForeignKeyField.remote_field` narrows to `ForeignKeyRel` so `remote_field.on_delete` is non-optional. `ForeignObjectRel`, `ForeignKeyRel`, and `ManyToManyRel` `__init__` are kwarg-only. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **Known limitation: data migrations + cascading deletes.** On a fresh `migrations apply`, FK constraints don't exist yet (they're added by convergence in step 3 of `postgres sync`). A `RunPython` data migration that calls `.delete()` on a parent with cascading children will orphan the children, and the subsequent convergence `VALIDATE` will fail. Existing databases are unaffected. Documented with a workaround in the Postgres README (delete children explicitly first, or use `RunSQL`). ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- **Rewrote the Schema management docs** to distinguish convergence, structural migrations, and data migrations by who authors the change and whether the framework can guarantee a safe apply. Added a per-change-type table covering safe apply patterns (`CREATE INDEX CONCURRENTLY`, `NOT VALID` + `VALIDATE`, etc.) and split the Migrations section into “Structural migrations” and “Data migrations.” ([8ae39e2cef78](https://github.com/dropseed/plain/commit/8ae39e2cef78), [49d2b2452dea](https://github.com/dropseed/plain/commit/49d2b2452dea))

### Upgrade instructions

- **Adapt callers of `.delete()`.** `.delete()` now returns an `int`, not a `(count, by_label)` tuple.
    - Before: `count, _ = qs.delete()` or `count = qs.delete()[0]`
    - After: `count = qs.delete()`
- **Rename `DO_NOTHING` to `NO_ACTION`** at all import and usage sites. Regenerate or hand-edit migration files that reference `DO_NOTHING`.
- **Replace `PROTECT` with `RESTRICT`.** Catch `psycopg.errors.IntegrityError` instead of `ProtectedError` / `RestrictedError`.
- **Replace `SET(callable)` usages.** There is no one-line equivalent — the Python-callable path doesn't exist in Postgres. Either switch to a supported action (`SET_NULL`, `RESTRICT`, `CASCADE`, `NO_ACTION`) or handle the affected rows explicitly before deletion.
- **Replace `SET_DEFAULT` usages.** Pick a different `on_delete`, or set the default explicitly in application code before deletion. `SET_DEFAULT` will return once Plain persists column defaults.
- **Run `plain postgres sync`** after upgrading. Convergence will install the correct `ON DELETE` clauses on existing FKs — no migration file, no manual step.
- **If you set `db_constraint=False` on a FK with a non-`NO_ACTION` `on_delete`**, change the action to `NO_ACTION` — preflight will now fail otherwise.
- **Review `RunPython` migrations that call `.delete()` on parents with cascading children.** On a fresh `migrations apply` before convergence runs, children become orphans and break the subsequent `VALIDATE`. Delete children explicitly first, or use `RunSQL`.

## [0.94.2](https://github.com/dropseed/plain/releases/plain-postgres@0.94.2) (2026-04-13)

### What's changed

- Updated internal references to use the fixed `app.users.models.User` convention. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- Migrated type suppression comments to `ty: ignore` for the new ty checker version. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- No changes required.

## [0.94.1](https://github.com/dropseed/plain/releases/plain-postgres@0.94.1) (2026-04-05)

### What's changed

- **Removed deprecated `db.user` attribute from query spans.** The attribute was removed from the OTel semconv with no replacement. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Switched `DbSystemValues` to stable `DbSystemNameValues`.** Migrated from the deprecated `opentelemetry.semconv.trace` module to the stable `opentelemetry.semconv.attributes.db_attributes`. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Added `error.type` attribute to query spans on exceptions.** Set to the fully-qualified exception class name (e.g. `psycopg.errors.UniqueViolation`) for queryable error grouping. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))
- **Removed `set_status(OK)` from query spans.** Per the OTel spec, instrumentation libraries should leave span status as Unset on success. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))

### Upgrade instructions

- No changes required.

## [0.94.0](https://github.com/dropseed/plain/releases/plain-postgres@0.94.0) (2026-04-02)

### What's changed

- **Undeclared indexes and constraints are now automatically dropped by `postgres sync` and `postgres converge`.** Models are the source of truth — if an index or constraint exists in the database but isn't declared on any model, convergence removes it. The `--drop-undeclared` flag has been removed from both commands. ([a74b6ab30c14](https://github.com/dropseed/plain/commit/a74b6ab30c14))

### Upgrade instructions

- Remove `--drop-undeclared` from any scripts or Procfiles that use `plain postgres sync` or `plain postgres converge`. Undeclared objects are now dropped automatically.

## [0.93.1](https://github.com/dropseed/plain/releases/plain-postgres@0.93.1) (2026-04-02)

### What's changed

- **Fixed `F.deconstruct()` failing with "Could not find object F in plain.postgres".** `F`, `Value`, `Func`, and other expression classes had `@deconstructible` paths pointing to `plain.postgres` but weren't exported from it, breaking migration serialization. `F` is now exported from `plain.postgres` (alongside `Q`), and the other classes use their actual module paths. ([5fdcb040](https://github.com/dropseed/plain/commit/5fdcb040))

- **Fixed false-positive convergence mismatches for expression-based unique constraints.** PostgreSQL's `pg_get_indexdef` adds type casts (e.g. `lower((slug)::text)`) and the ORM wraps each expression in parentheses — `normalize_expression()` now strips both, preventing spurious "definition changed" errors during `postgres sync`. ([b734205268](https://github.com/dropseed/plain/commit/b734205268))

- **Removed constraints and indexes from migration options.** These were serialized into migration files but never used during execution — convergence reads from the live model class. Removing them eliminates unnecessary serialization of complex expressions like `Lower()` and reduces migration file noise. ([82e5a880](https://github.com/dropseed/plain/commit/82e5a880))

### Upgrade instructions

- No changes required. Existing migrations with constraints/indexes in their options will continue to load fine.

## [0.93.0](https://github.com/dropseed/plain/releases/plain-postgres@0.93.0) (2026-04-01)

### What's changed

- **Added `db.client.operation.duration` OTel histogram for database query timing.** Every query executed through `db_span()` now records its duration as an OpenTelemetry histogram metric, following the [semantic conventions](https://opentelemetry.io/docs/specs/semconv/db/database-metrics/) for database client metrics. Attributes include `db.system.name`, `db.operation.name`, and `db.collection.name`. Without a configured `MeterProvider`, this is a no-op with zero overhead. ([56c2f993b88c](https://github.com/dropseed/plain/commit/56c2f993b88c))

### Upgrade instructions

- No changes required.

## [0.92.1](https://github.com/dropseed/plain/releases/plain-postgres@0.92.1) (2026-03-30)

### What's changed

- **Fixed false-positive "definition differs" for UniqueConstraint with expressions and conditions.** A `UniqueConstraint` using both expressions (e.g. `Lower("username")`) and a `condition` (e.g. `~Q(username="")`) was incorrectly flagged as drifted. PostgreSQL adds type casts (`''::text`) and the ORM adds extra parentheses around expressions — the old full-SQL-string comparison couldn't reconcile these differences. ([e03f3496a49a](https://github.com/dropseed/plain/commit/e03f3496a49a))

- **Replaced fragile full-SQL comparison with structured comparison for all index and constraint definitions.** Instead of normalizing entire `CREATE INDEX` statements, convergence now parses `pg_get_indexdef` output into components (expression text, columns, opclasses, WHERE clause) and compares each independently. Both regular indexes and unique constraints share a single comparison core. ([e03f3496a49a](https://github.com/dropseed/plain/commit/e03f3496a49a))

### Upgrade instructions

- No changes required.

## [0.92.0](https://github.com/dropseed/plain/releases/plain-postgres@0.92.0) (2026-03-30)

### What's changed

- **Foreign key constraints are now managed by convergence, not migrations.** The schema editor no longer creates, drops, or alters FK constraints — convergence handles them declaratively using `ADD CONSTRAINT ... NOT VALID` followed by `VALIDATE CONSTRAINT`. FK constraint names are deterministic and match the old migration-generated names. ([b2b968297fea](https://github.com/dropseed/plain/commit/b2b968297fea), [8658be035a46](https://github.com/dropseed/plain/commit/8658be035a46))

- **NOT NULL enforcement is now managed by convergence.** Column nullability drift is detected and fixed automatically — convergence uses the safe `CHECK NOT VALID → VALIDATE → SET NOT NULL` pattern to avoid long table locks. Columns with existing NULL rows are reported as blocked, requiring a backfill before convergence can proceed. ([5ea3dc589453](https://github.com/dropseed/plain/commit/5ea3dc589453))

- **Managed type boundaries** — convergence now distinguishes managed vs unmanaged index types and constraint types. Only btree/hash indexes and check/unique/FK constraints participate in drift detection and rename matching. Unmanaged types (GIN, GiST, BRIN, exclusion, trigger) are displayed for informational purposes but are never modified or reported as undeclared. ([f123eae2fa56](https://github.com/dropseed/plain/commit/f123eae2fa56))

- **Unique constraint drift detection** — convergence now compares unique constraint definitions (not just column lists), detecting behavioral changes like modified WHERE clauses, opclasses, or expressions. Index-only uniques (partial, expression, or opclass) are correctly handled through both pg_constraint and pg_index. ([09b439e8448a](https://github.com/dropseed/plain/commit/09b439e8448a))

- **Full index definition matching** — index drift detection now compares normalized `CREATE INDEX` definitions instead of just column lists, catching changes to conditions, expressions, opclasses, and include columns. ([70d7a6725498](https://github.com/dropseed/plain/commit/70d7a6725498))

- Removed dead index/constraint/deferred SQL infrastructure and primary-key transition code from the schema editor. ([266b0635f0bf](https://github.com/dropseed/plain/commit/266b0635f0bf), [4a92f5479e4e](https://github.com/dropseed/plain/commit/4a92f5479e4e))

- Rewrote the introspection layer to mirror Postgres catalog structures — `TableState` now uses a unified `constraints` dict keyed by constraint name with `ConType` enum, replacing the separate `unique_constraints`, `check_constraints`, and `foreign_keys` dicts. ([f123eae2fa56](https://github.com/dropseed/plain/commit/f123eae2fa56))

- Expanded schema management documentation with a comprehensive overview of the migrations + convergence split, sync workflow, and convergence behavior. ([57caeee5ff89](https://github.com/dropseed/plain/commit/57caeee5ff89))

### Upgrade instructions

- If you have custom code that interacts with `TableState.unique_constraints`, `TableState.check_constraints`, or `TableState.foreign_keys`, update it to use the unified `TableState.constraints` dict with `ConType` filtering instead.
- FK constraints in existing databases are left as-is. New FKs will be created by convergence on the next `postgres sync`.
- NOT NULL enforcement is automatic — `postgres sync` will detect and fix nullability drift. If columns have existing NULL rows, you'll need to backfill before convergence can apply NOT NULL.

## [0.91.1](https://github.com/dropseed/plain/releases/plain-postgres@0.91.1) (2026-03-29)

### What's changed

- Indented `sync` and `converge` sub-items under section headers for readability in environments without ANSI colors (e.g. Heroku deploy logs). ([b6b494dcc698](https://github.com/dropseed/plain/commit/b6b494dcc698))
- `sync` now uses `MigrationExecutor` directly instead of calling through the CLI layer, giving cleaner indented output. ([b6b494dcc698](https://github.com/dropseed/plain/commit/b6b494dcc698))

### Upgrade instructions

- No changes required.

## [0.91.0](https://github.com/dropseed/plain/releases/plain-postgres@0.91.0) (2026-03-29)

### What's changed

- **New `postgres sync` command** — the primary command for both development and deployment. In DEBUG mode it creates migrations, applies them, and converges. In production it applies migrations and converges. Use `--check` in CI to verify the database is fully synced. ([b026895edc4c](https://github.com/dropseed/plain/commit/b026895edc4c), [b348a5af0867](https://github.com/dropseed/plain/commit/b348a5af0867))

- **Indexes and constraints are now managed by convergence, not migrations.** The migration autodetector no longer generates `AddIndex`, `RemoveIndex`, `RenameIndex`, `AddConstraint`, or `RemoveConstraint` operations — these classes have been removed. Convergence (`postgres sync` or `postgres converge`) creates, renames, rebuilds, and validates indexes and constraints using safe strategies: `CREATE INDEX CONCURRENTLY`, `NOT VALID` + `VALIDATE CONSTRAINT` for check constraints, and `CONCURRENTLY` + `USING INDEX` for unique constraints. ([c58b4ba1fec9](https://github.com/dropseed/plain/commit/c58b4ba1fec9), [f6506d263f3f](https://github.com/dropseed/plain/commit/f6506d263f3f), [1f15538b008f](https://github.com/dropseed/plain/commit/1f15538b008f))

- **Command renames**: `makemigrations` → `migrations create`, `migrate` → `migrations apply`. The old top-level `makemigrations` and `migrate` shortcuts have been removed. ([adf021688bf3](https://github.com/dropseed/plain/commit/adf021688bf3))

- **Removed `--backup` flag from `migrations apply`** — database backups have moved to `plain-dev`. ([50773a50f674](https://github.com/dropseed/plain/commit/50773a50f674))

- **Removed `PositiveIntegerField`, `PositiveBigIntegerField`, and `PositiveSmallIntegerField`** — use `IntegerField`, `BigIntegerField`, or `SmallIntegerField` with a `CheckConstraint` if you need positivity enforcement. The `db_check` pipeline has also been removed. ([738a1efbca59](https://github.com/dropseed/plain/commit/738a1efbca59))

- **Convergence overhaul** — rewritten into analysis, planning, and execution layers. Now detects index/constraint renames, stale definitions, INVALID indexes, and NOT VALID constraints. Each fix is applied and committed independently so partial failures don't block subsequent fixes. The `--prune` flag has been renamed to `--drop-undeclared`, which distinguishes between indexes (non-blocking) and constraints (blocking) when undeclared objects remain. ([987791d345cb](https://github.com/dropseed/plain/commit/987791d345cb), [66ac1152be0d](https://github.com/dropseed/plain/commit/66ac1152be0d), [f2f46e1a6054](https://github.com/dropseed/plain/commit/f2f46e1a6054), [5bb1472acf0f](https://github.com/dropseed/plain/commit/5bb1472acf0f))

- Fixed test database names exceeding Postgres's 63-character identifier limit. ([4a8937ba2758](https://github.com/dropseed/plain/commit/4a8937ba2758))

### Upgrade instructions

1. **Replace `migrate` with `postgres sync` in deploy scripts and CI.** `postgres sync` applies migrations and runs convergence in a single step. For CI checks, use `postgres sync --check` instead of `migrate --check` / `makemigrations --check`. The lower-level commands are still available as `migrations create` and `migrations apply`.

2. **Remove index/constraint operations from migration files.** Delete any `AddIndex`, `RemoveIndex`, `RenameIndex`, `AddConstraint`, and `RemoveConstraint` operations from your migration files — these classes no longer exist and will cause import errors. It's fine to leave a migration with `operations = []`. Indexes and constraints declared on your models will be created automatically by convergence.

3. **Replace `PositiveIntegerField`** (and `PositiveBigIntegerField`, `PositiveSmallIntegerField`) with `IntegerField` (or `BigIntegerField`, `SmallIntegerField`) in both models and migration files. Add a `CheckConstraint` if you need to enforce positive values.

4. **Run `plain postgres sync`** after upgrading to create indexes and constraints via convergence.

5. If you used `plain postgres backups`, install `plain-dev>=0.60.0` — backups have moved to `plain dev backups`.

## [0.90.0](https://github.com/dropseed/plain/releases/plain-postgres@0.90.0) (2026-03-28)

### What's changed

- **Removed `CharField`** — use `TextField` for all string fields. PostgreSQL treats `varchar` and `text` identically (same storage, same performance), so the distinction was unnecessary. `TextField` now accepts an optional `max_length` for Python-side validation via `MaxLengthValidator`, without affecting the database column type. ([5062ee4dd1fd](https://github.com/dropseed/plain/commit/5062ee4dd1fd))
- **`EmailField` and `URLField` now extend `TextField`** instead of `CharField`. Their default `max_length` values (254 and 200 respectively) have been removed — pass `max_length` explicitly if you need validation. ([5062ee4dd1fd](https://github.com/dropseed/plain/commit/5062ee4dd1fd))
- **Simplified field class internals** — removed the `get_internal_type()` method and 6 lookup dicts from `dialect.py`. Each field class now declares its SQL type directly via `db_type_sql` class attribute. String-based type comparisons replaced with `isinstance()` checks throughout. ([3ffdebe22250](https://github.com/dropseed/plain/commit/3ffdebe22250))
- **Added `postgres converge` command** — detects and fixes safe schema mismatches between models and the database. Currently handles `character varying` → `text` conversions. ([fe8cf3995e95](https://github.com/dropseed/plain/commit/fe8cf3995e95))

### Upgrade instructions

- Replace `CharField` with `TextField` in model code (e.g. `types.CharField(max_length=100)` → `types.TextField(max_length=100)`)
- Replace `CharField` with `TextField` in migration files (e.g. `postgres.CharField(max_length=255)` → `postgres.TextField(max_length=255)`)
- If you subclass `CharField`, change the parent class to `TextField`
- `EmailField` no longer defaults `max_length=254` and `URLField` no longer defaults `max_length=200` — remove these from migration files if present (e.g. `postgres.EmailField(max_length=254)` → `postgres.EmailField()`)
- Run `plain postgres converge` to convert existing `character varying` columns to `text` (in development and production). The conversion is instant and safe — PostgreSQL treats them identically. Use `--yes` to skip confirmation in CI/deploy scripts.

## [0.89.2](https://github.com/dropseed/plain/releases/plain-postgres@0.89.2) (2026-03-27)

### What's changed

- Fixed `schema` command miscategorizing expression-based unique constraints as missing columns ([93ab244416f8](https://github.com/dropseed/plain/commit/93ab244416f8))
- Used canonical Postgres type names in `DATA_TYPES` mapping, removing the `_normalize_type` helper ([f581fe6009bd](https://github.com/dropseed/plain/commit/f581fe6009bd))
- Moved `diagnose/` module to `introspection/`, consolidated into 2 files, added schema introspection functions used by `schema` and `drop-unknown-tables` commands ([86f7f5b85a87](https://github.com/dropseed/plain/commit/86f7f5b85a87))
- `diagnose --json` now exits 0 — the JSON data is the signal, not the exit code ([86f7f5b85a87](https://github.com/dropseed/plain/commit/86f7f5b85a87))
- Added migration reset documentation for replacing migration history with a fresh `0001_initial` ([2fa6203379e9](https://github.com/dropseed/plain/commit/2fa6203379e9))
- Updated form field references from `CharField` to `TextField` in model forms ([4e29f5d6cade](https://github.com/dropseed/plain/commit/4e29f5d6cade))
- Changed CLI confirmation flags to `--yes`/`-y` across all commands ([0af36e101f03](https://github.com/dropseed/plain/commit/0af36e101f03))

### Upgrade instructions

- Requires `plain>=0.129.0`. If you use `plain postgres diagnose --json` exit codes in CI, note that it now always exits 0 — check the JSON output for issues instead.

## [0.89.1](https://github.com/dropseed/plain/releases/plain-postgres@0.89.1) (2026-03-26)

### What's changed

- Fixed `schema` command type mismatches for `time`, `timestamp`, and `DecimalField` types that caused false drift reports ([187e39e3faeb](https://github.com/dropseed/plain/commit/187e39e3faeb))
- Fixed `schema` command crash on expression-based unique constraints (e.g. `UniqueConstraint` with `expressions` instead of `fields`) ([187e39e3faeb](https://github.com/dropseed/plain/commit/187e39e3faeb))
- Improved 0.89.0 upgrade instructions with clearer ordering and step descriptions ([a59062327ed5](https://github.com/dropseed/plain/commit/a59062327ed5), [c0520bdca709](https://github.com/dropseed/plain/commit/c0520bdca709))

### Upgrade instructions

- No changes required.

## [0.89.0](https://github.com/dropseed/plain/releases/plain-postgres@0.89.0) (2026-03-25)

### What's changed

- **Removed `db_index` from `ForeignKeyField`** — FK fields no longer create indexes automatically. Declare an explicit `Index(fields=["field"], name="...")` for any FK column that needs one. The `db_index` parameter has been removed entirely. ([061b97f5d538](https://github.com/dropseed/plain/commit/061b97f5d538))
- **Removed `Index.set_name_with_model()`** — the hash-based auto-naming machinery is gone. `Index.name` is now validated as non-empty at construction time. ([9a4ecf8ac2f0](https://github.com/dropseed/plain/commit/9a4ecf8ac2f0))
- **Index/constraint name collision detection** — preflight now checks index and constraint names together (they share the same Postgres namespace), catching cross-type collisions that would fail at migrate time. ([292f8d6791d6](https://github.com/dropseed/plain/commit/292f8d6791d6))
- **New `plain postgres schema` command** — shows expected DB schema from model definitions and compares it against the actual database. Detects column type mismatches, nullability drift, missing/extra columns, and orphan indexes. Use `--check` for CI (exits non-zero on drift). ([ee336078483f](https://github.com/dropseed/plain/commit/ee336078483f))

### Upgrade instructions

1. Remove any `db_index=False` from FK fields in models and migration files — the parameter no longer exists.

2. For each `ForeignKeyField`, check if it's covered by an explicit `Index` or `UniqueConstraint` (with the FK as the leading field). Most FK columns should have an index.

3. **If uncovered**, add an explicit index:

    ```python
    model_options = postgres.Options(
        indexes=[
            postgres.Index(name="myapp_mymodel_author_id_idx", fields=["author"]),
        ],
    )
    ```

4. Run `makemigrations`. Before the `AddIndex` operation, add a `RunSQL` to drop the orphan auto-index left behind by the old `db_index=True` default:

    ```python
    operations = [
        migrations.RunSQL('DROP INDEX IF EXISTS "myapp_mymodel_author_id_abc12345"'),
        migrations.AddIndex(...),
    ]
    ```

    The old auto-index name follows the pattern `{table}_{column}_{hash}`. Find orphan names by running `plain postgres schema`.

5. **If already covered** by a composite index or unique constraint, the orphan auto-index is redundant. Generate a migration to drop it:

    ```python
    operations = [
        migrations.RunSQL('DROP INDEX IF EXISTS "myapp_mymodel_author_id_abc12345"'),
    ]
    ```

6. Run `migrate`.

## [0.88.2](https://github.com/dropseed/plain/releases/plain-postgres@0.88.2) (2026-03-25)

### What's changed

- Actually enforce `name` as a required keyword argument on `Index.__init__` — 0.88.0 documented the requirement but the code enforcement was missing from the release.

### Upgrade instructions

- See 0.88.0 upgrade instructions.

## [0.88.1](https://github.com/dropseed/plain/releases/plain-postgres@0.88.1) (2026-03-25)

_Yanked — code change missing, see 0.88.2._

## [0.88.0](https://github.com/dropseed/plain/releases/plain-postgres@0.88.0) (2026-03-25)

### What's changed

- **`Index` now requires a `name` argument** — auto-naming (`set_name_with_model`) is no longer used for new indexes. Use the `{table}_{column(s)}_idx` convention (e.g., `plainjobs_jobrequest_priority_idx`). ([74aa8b76aa40](https://github.com/dropseed/plain/commit/74aa8b76aa40))
- Raised `Index.max_name_length` from 30 to 63 to match Postgres's actual identifier limit (`NAMEDATALEN - 1`). The old limit was inherited from Django's multi-database support. ([74aa8b76aa40](https://github.com/dropseed/plain/commit/74aa8b76aa40))

### Upgrade instructions

- Add `name=` to all `Index` objects in your models. Use the `{table}_{column}_idx` convention. Run `makemigrations` — it will auto-generate `RenameIndex` operations (instant `ALTER INDEX RENAME`, no locks). Then run `migrate`.

## [0.87.0](https://github.com/dropseed/plain/releases/plain-postgres@0.87.0) (2026-03-25)

### What's changed

- **Renamed `plain db` CLI to `plain postgres`** — all subcommands (`migrate`, `diagnose`, `wait`, `backups`, etc.) are now under `plain postgres` ([a639aeacbf8d](https://github.com/dropseed/plain/commit/a639aeacbf8d))
- **Extracted diagnose checks into `plain.postgres.diagnose` package** — the monolithic diagnose module is now split into individual check modules for better maintainability ([91f354108202](https://github.com/dropseed/plain/commit/91f354108202))
- **FK-aware index checks** — duplicate index detection now recognizes that FK fields auto-create indexes, avoiding false positives when a composite index covers the FK column ([c116f808ac0b](https://github.com/dropseed/plain/commit/c116f808ac0b))
- Added Diagnostics documentation section to README with check details, thresholds, and production usage guidance ([c116f808ac0b](https://github.com/dropseed/plain/commit/c116f808ac0b))
- Show slow queries in diagnose human-readable output and fix Heroku command quoting in the diagnose skill ([6feaad54065d](https://github.com/dropseed/plain/commit/6feaad54065d))

### Upgrade instructions

- Replace `plain db` with `plain postgres` in all scripts, CI configs, and documentation. The old `plain db` command no longer exists.

## [0.86.0](https://github.com/dropseed/plain/releases/plain-postgres@0.86.0) (2026-03-24)

### What's changed

- **New `plain db diagnose` command** — runs health checks against your Postgres database and reports issues as structured JSON. Checks for unused indexes, duplicate indexes, missing foreign key indexes, sequence exhaustion, transaction ID wraparound, vacuum health, and slow queries (via `pg_stat_statements`). Each finding includes table ownership info (app vs package) and actionable suggestions ([91994604b60d](https://github.com/dropseed/plain/commit/91994604b60d))
- **New preflight checks** for missing foreign key indexes and duplicate indexes — these run automatically during `plain check` and flag issues before they hit production ([3703fe8ab38d](https://github.com/dropseed/plain/commit/3703fe8ab38d))
- New `plain-postgres-diagnose` AI skill for guided database health check workflow ([91994604b60d](https://github.com/dropseed/plain/commit/91994604b60d))

### Upgrade instructions

- No changes required.

## [0.85.0](https://github.com/dropseed/plain/releases/plain-postgres@0.85.0) (2026-03-22)

### What's changed

- Added read-only database connection support via `read_only()` context manager and `connection.set_read_only()` — enforces `SET default_transaction_read_only = ON` so any write attempt raises a database error ([69d23b04fde9](https://github.com/dropseed/plain/commit/69d23b04fde9))
- Removed PEP-249 exception mirror — `IntegrityError`, `OperationalError`, `ProgrammingError`, etc. are no longer re-exported from `plain.postgres`. Use `psycopg` exceptions directly (e.g. `psycopg.IntegrityError`) ([d4b170e60a2c](https://github.com/dropseed/plain/commit/d4b170e60a2c))
- Removed `DatabaseErrorWrapper` context manager — psycopg's native connection state handling replaces it ([015b04ce38e9](https://github.com/dropseed/plain/commit/015b04ce38e9))
- Added transaction and read-only connection documentation to README

### Upgrade instructions

- Replace any `from plain.postgres import IntegrityError` (or `OperationalError`, `ProgrammingError`, etc.) with `import psycopg` and use `psycopg.IntegrityError` directly.
- Replace any usage of `plain.postgres.db.DatabaseErrorWrapper` with standard `try/except` on psycopg exceptions.

## [0.84.2](https://github.com/dropseed/plain/releases/plain-postgres@0.84.2) (2026-03-20)

### What's changed

- Migrated all internal logging to structured format using `get_framework_logger()` and flat `extra={}` dicts instead of inline string formatting — log messages are now short descriptive labels (e.g. "Query executed", "Transaction command") with structured metadata (`sql`, `params`, `duration`, etc.) passed separately ([75a8b60c91](https://github.com/dropseed/plain/commit/75a8b60c91))

### Upgrade instructions

- No changes required.

## [0.84.1](https://github.com/dropseed/plain/releases/plain-postgres@0.84.1) (2026-03-16)

### What's changed

- Renamed `_nodb_cursor` to `_maintenance_cursor` for clarity — it now always connects to the `postgres` database directly instead of falling back through multiple connection strategies ([27bdee72d03e](https://github.com/dropseed/plain/commit/27bdee72d03e), [f15b46ede57d](https://github.com/dropseed/plain/commit/f15b46ede57d))
- `DATABASE` config key is now required (validated at configure time) rather than allowing `None`/empty string with runtime fallbacks ([f15b46ede57d](https://github.com/dropseed/plain/commit/f15b46ede57d))

### Upgrade instructions

- No changes required.

## [0.84.0](https://github.com/dropseed/plain/releases/plain-postgres@0.84.0) (2026-03-12)

### What's changed

- Renamed package from `plain-models` to `plain-postgres` — the pip package, module path, and package label (`plainmodels` to `plainpostgres`) all reflect the PostgreSQL-only scope.
- All internal imports updated from `plain.models` to `plain.postgres`.
- Flattened `plain.models.postgres` subpackage into top-level `plain.postgres`.

### Upgrade instructions

- Update imports: `from plain.models` to `from plain.postgres`, `from plain import models` to `from plain import postgres`.
- In `pyproject.toml`, change `plain-models` to `plain-postgres` and `plain.models` to `plain.postgres` in dependencies.
- In `INSTALLED_PACKAGES`, change `"plain.models"` to `"plain.postgres"`.

## [0.83.0](https://github.com/dropseed/plain/releases/plain-postgres@0.83.0) (2026-03-12)

### What's changed

- Renamed `plain.models` to `plain.postgres` — the package name now reflects its PostgreSQL-only scope.
- Flattened the `plain.models.postgres` subpackage — all internal modules now live at the top level.

### Upgrade instructions

- Change `from plain import models` → `from plain import postgres` and update all `models.X` usages to `postgres.X` (e.g. `postgres.Model`, `postgres.register_model`, `postgres.CASCADE`).
- Change `from plain.models import ...` → `from plain.postgres import ...`.
- In `pyproject.toml`, change `plain.models` → `plain.postgres` and `plain-models` → `plain-postgres` in dependencies.
- In `INSTALLED_PACKAGES`, change `"plain.models"` → `"plain.postgres"`.

## [0.82.3](https://github.com/dropseed/plain/releases/plain-models@0.82.3) (2026-03-10)

### What's changed

- Removed `type: ignore` comments on `POSTGRES_PASSWORD` default values, now that `Secret` is type-transparent ([997afd9a558f](https://github.com/dropseed/plain/commit/997afd9a558f))
- Adopted PEP 695 type parameter syntax across `Field`, `QuerySet`, `register_model`, type stubs, and other generics ([aa5b2db6e8ed](https://github.com/dropseed/plain/commit/aa5b2db6e8ed))
- Added migration docs reminder to AI rules ([09deb5d5a382](https://github.com/dropseed/plain/commit/09deb5d5a382))

### Upgrade instructions

- No changes required.

## [0.82.2](https://github.com/dropseed/plain/releases/plain-models@0.82.2) (2026-03-10)

### What's changed

- Updated all README code examples to use `types.*` with Python type annotations as the default pattern ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))
- Removed separate "Typed fields" and "Typing reverse relationships" doc sections — typed fields are now the default in all examples ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))
- Added "Field Imports" section and "Differences from Django" section to AI rules ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))
- Broadened AI rules to apply to all Python files, not just model files ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))

### Upgrade instructions

- No changes required.

## [0.82.1](https://github.com/dropseed/plain/releases/plain-models@0.82.1) (2026-03-10)

### What's changed

- Replaced `SET()` closure with a `_SetOnDelete` class to eliminate `type: ignore` comments for dynamic attribute assignment (`deconstruct`, `lazy_sub_objs`) ([cda461b1b4f6](https://github.com/dropseed/plain/commit/cda461b1b4f6))
- Replaced `lazy_sub_objs` function attribute on `SET_NULL` and `SET_DEFAULT` with a module-level `_LAZY_ON_DELETE` set ([cda461b1b4f6](https://github.com/dropseed/plain/commit/cda461b1b4f6))
- Narrowed `_relation_tree` type and used `get_forward_field` in migration operations ([eb5af6a525b5](https://github.com/dropseed/plain/commit/eb5af6a525b5))
- Type annotation improvements across expressions, indexes, related fields, and deletion modules ([f56c6454b164](https://github.com/dropseed/plain/commit/f56c6454b164))

### Upgrade instructions

- No changes required.

## [0.82.0](https://github.com/dropseed/plain/releases/plain-models@0.82.0) (2026-03-09)

### What's changed

- Added `EncryptedTextField` and `EncryptedJSONField` for transparent encryption at rest using Fernet (AES-128-CBC + HMAC-SHA256) with keys derived from `SECRET_KEY` ([73f3534f9334](https://github.com/dropseed/plain/commit/73f3534f9334))
- Encrypted fields support key rotation via `SECRET_KEY_FALLBACKS` and gradual migration from plaintext columns ([73f3534f9334](https://github.com/dropseed/plain/commit/73f3534f9334))
- Preflight checks prevent encrypted fields from being used in indexes or constraints ([73f3534f9334](https://github.com/dropseed/plain/commit/73f3534f9334))

### Upgrade instructions

- No changes required. Install the `cryptography` package to use the new encrypted fields.

## [0.81.1](https://github.com/dropseed/plain/releases/plain-models@0.81.1) (2026-03-09)

### What's changed

- Use `connection.execute()` instead of opening a cursor for internal one-off queries (timezone configuration, role assumption, connection health checks) ([828d665979df](https://github.com/dropseed/plain/commit/828d665979df))

### Upgrade instructions

- No changes required.

## [0.81.0](https://github.com/dropseed/plain/releases/plain-models@0.81.0) (2026-03-09)

### What's changed

- **psycopg3 `cursor.stream()` for iterator queries** — `QuerySet.iterator()` now uses psycopg3's native server-side streaming instead of `fetchmany()` chunking, reducing memory overhead for large result sets ([49f4d1d996b4](https://github.com/dropseed/plain/commit/49f4d1d996b4))
- **Minimum PostgreSQL 16 enforced** — a preflight check now validates the connected PostgreSQL version is 16 or higher ([e1f21c4b251a](https://github.com/dropseed/plain/commit/e1f21c4b251a))
- **Renamed `DatabaseWrapper` → `DatabaseConnection`** and moved from `postgres/wrapper.py` to `postgres/connection.py` to better reflect the class's purpose ([7f17a96a7f8e](https://github.com/dropseed/plain/commit/7f17a96a7f8e), [4a79279d01dd](https://github.com/dropseed/plain/commit/4a79279d01dd))
- **Replaced `db_connection` proxy with `get_connection()`** — the stateless `DatabaseConnection` proxy class is removed in favor of module-level `get_connection()` and `has_connection()` functions, giving type checkers direct access to the real `DatabaseConnection` class and eliminating proxy overhead ([4a79279d01dd](https://github.com/dropseed/plain/commit/4a79279d01dd))
- **Replaced `threading.local()` with `ContextVar` for DB connection storage** — database connections are now stored per-context instead of per-thread, enabling proper async support ([cc2469b1260a](https://github.com/dropseed/plain/commit/cc2469b1260a))
- Removed `validate_thread_sharing()` from `DatabaseConnection` — thread sharing validation is no longer needed with ContextVar-based connection storage ([3a6d6efd09d2](https://github.com/dropseed/plain/commit/3a6d6efd09d2))
- Extracted `get_converters()` and `apply_converters()` as standalone functions from `SQLCompiler` and added type annotations ([ed18d3c97142](https://github.com/dropseed/plain/commit/ed18d3c97142))

### Upgrade instructions

- Replace `from plain.models import db_connection` with `from plain.models import get_connection`, and change `db_connection.cursor()` to `get_connection().cursor()` (and similar attribute access).
- If you imported `DatabaseWrapper`, it is now `DatabaseConnection` from `plain.models.postgres.connection`.
- PostgreSQL 16 or higher is now required.

## [0.80.0](https://github.com/dropseed/plain/releases/plain-models@0.80.0) (2026-02-25)

### What's changed

- Replaced the `DATABASE` dict setting with individual `POSTGRES_*` settings (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DATABASE`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, etc.) configurable via `PLAIN_POSTGRES_*` environment variables or `app/settings.py` ([e3c5a32d4da6](https://github.com/dropseed/plain/commit/e3c5a32d4da6))
- `DATABASE_URL` still works and takes priority — individual settings are parsed from it automatically ([e3c5a32d4da6](https://github.com/dropseed/plain/commit/e3c5a32d4da6))
- Added `DATABASE_URL=none` to explicitly disable the database (e.g. during Docker builds) ([e3c5a32d4da6](https://github.com/dropseed/plain/commit/e3c5a32d4da6))
- Removed the `AUTOCOMMIT` config setting — Plain always runs with autocommit=True ([5dc1995615d9](https://github.com/dropseed/plain/commit/5dc1995615d9))
- Refactored backup client internals with shared `_get_conn_args()` and `_run()` helpers ([e3c5a32d4da6](https://github.com/dropseed/plain/commit/e3c5a32d4da6))

### Upgrade instructions

- If you use `DATABASE_URL`, no changes are required — it continues to work as before.
- If you manually defined the `DATABASE` dict in settings, replace it with individual `POSTGRES_*` settings:

    ```python
    # Before
    DATABASE = {"NAME": "mydb", "USER": "me", "HOST": "localhost"}

    # After
    POSTGRES_DATABASE = "mydb"
    POSTGRES_USER = "me"
    POSTGRES_HOST = "localhost"
    ```

- The `DATABASE` dict key `"NAME"` is now `"DATABASE"` internally — update any code that accessed `settings_dict["NAME"]` directly.
- Remove any `AUTOCOMMIT` setting from your database config — it is no longer recognized.

## [0.79.0](https://github.com/dropseed/plain/releases/plain-models@0.79.0) (2026-02-24)

### What's changed

- Added `plain db drop-unknown-tables` command to remove database tables not associated with any Plain model ([108b0bce59e6](https://github.com/dropseed/plain/commit/108b0bce59e6))
- The unknown-tables preflight warning now suggests running `plain db drop-unknown-tables` instead of manual SQL ([108b0bce59e6](https://github.com/dropseed/plain/commit/108b0bce59e6))

### Upgrade instructions

- No changes required.

## [0.78.0](https://github.com/dropseed/plain/releases/plain-models@0.78.0) (2026-02-16)

### What's changed

- **PostgreSQL is now the only supported database** — MySQL and SQLite backends have been removed ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))
- The `ENGINE` key has been removed from the `DATABASE` setting — it is no longer needed since PostgreSQL is implicit ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))
- Database backends consolidated from `backends/base/`, `backends/postgresql/`, `backends/mysql/`, and `backends/sqlite3/` into a single `postgres/` module ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))
- Removed `DatabaseOperations` indirection layer — compilers are now created directly by `Query.get_compiler()` ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))
- Removed backend feature flags and multi-database conditional code throughout expressions, aggregates, schema editor, and migrations ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))
- Installation now recommends `uv add plain.models psycopg[binary]` to include the PostgreSQL driver ([6f3a066bf80f](https://github.com/dropseed/plain/commit/6f3a066bf80f))

### Upgrade instructions

- Remove `"ENGINE"` from your `DATABASE` setting — it will be ignored
- If you were using MySQL or SQLite, you must migrate to PostgreSQL
- Update any imports from `plain.models.backends.base` or `plain.models.backends.postgresql` to `plain.models.postgres`
- Install a PostgreSQL driver if you haven't already: `uv add psycopg[binary]`

## [0.77.1](https://github.com/dropseed/plain/releases/plain-models@0.77.1) (2026-02-13)

### What's changed

- Added migration development workflow documentation covering how to consolidate uncommitted and committed migrations ([0b30f98b5346](https://github.com/dropseed/plain/commit/0b30f98b5346))
- Added migration cleanup guidance to agent rules: consolidate before committing, use squash only for deployed migrations ([0b30f98b5346](https://github.com/dropseed/plain/commit/0b30f98b5346))

### Upgrade instructions

- No changes required.

## [0.77.0](https://github.com/dropseed/plain/releases/plain-models@0.77.0) (2026-02-13)

### What's changed

- `makemigrations --dry-run` now shows a SQL preview of the statements each migration would execute, making it easier to review schema changes before writing migration files ([c994703f9a28](https://github.com/dropseed/plain/commit/c994703f9a28))
- `makemigrations` now warns when packages have models but no `migrations/` directory, which can cause "No changes detected" confusion for new apps ([c994703f9a28](https://github.com/dropseed/plain/commit/c994703f9a28))
- Restructured README documentation: consolidated Querying section with Custom QuerySets, Typing, and Raw SQL; added N+1 avoidance and query efficiency subsections; reorganized Relationships and Constraints into clearer sections with schema design guidance ([f5d2731ebda0](https://github.com/dropseed/plain/commit/f5d2731ebda0), [8c2189a896d2](https://github.com/dropseed/plain/commit/8c2189a896d2))
- Slimmed agent rules to concise bullet reminders with `paths:` scoping for `**/models.py` files ([f5d2731ebda0](https://github.com/dropseed/plain/commit/f5d2731ebda0))

### Upgrade instructions

- No changes required.

## [0.76.5](https://github.com/dropseed/plain/releases/plain-models@0.76.5) (2026-02-12)

### What's changed

- Updated README model validation example to use `@models.register_model`, `UniqueConstraint`, and `model_options` ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))
- Added schema planning guidance to agent rules ([eaf55cb1b893](https://github.com/dropseed/plain/commit/eaf55cb1b893))

### Upgrade instructions

- No changes required.

## [0.76.4](https://github.com/dropseed/plain/releases/plain-models@0.76.4) (2026-02-04)

### What's changed

- Added `__all__` exports to `expressions` module for explicit public API boundaries ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Refactored internal imports to use explicit module paths instead of the `sql` namespace ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Updated agent rules to use `--api` instead of `--symbols` for `plain docs` command ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- No changes required.

## [0.76.3](https://github.com/dropseed/plain/releases/plain-models@0.76.3) (2026-02-02)

### What's changed

- Fixed observer query summaries for SQL statements starting with parentheses (e.g., UNION queries) by stripping leading `(` before extracting the operation ([bfbcb5a256f2](https://github.com/dropseed/plain/commit/bfbcb5a256f2))
- UNION queries now display with a "UNION" suffix in query summaries for better identification ([bfbcb5a256f2](https://github.com/dropseed/plain/commit/bfbcb5a256f2))
- Agent rules now include query examples showing the `Model.query` pattern ([02e11328dbf5](https://github.com/dropseed/plain/commit/02e11328dbf5))

### Upgrade instructions

- No changes required.

## [0.76.2](https://github.com/dropseed/plain/releases/plain-models@0.76.2) (2026-01-28)

### What's changed

- Converted the `plain-models` skill to a passive `.claude/rules/` file ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory.

## [0.76.1](https://github.com/dropseed/plain/releases/plain-models@0.76.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.76.0](https://github.com/dropseed/plain/releases/plain-models@0.76.0) (2026-01-22)

### What's changed

- Removed the `db_column` field parameter - column names are now always derived from the field name ([eed1bb6](https://github.com/dropseed/plain/commit/eed1bb6811))
- Removed the `db_collation` field parameter from `CharField` and `TextField` - use raw SQL or database-level collation settings instead ([49b362d](https://github.com/dropseed/plain/commit/49b362d3d3))
- Removed the `Collate` database function from `plain.models.functions` ([49b362d](https://github.com/dropseed/plain/commit/49b362d3d3))
- Removed the `db_comment` field parameter and `db_table_comment` model option - database comments are no longer supported ([eb5aabb](https://github.com/dropseed/plain/commit/eb5aabb5ca))
- Removed the `AlterModelTableComment` migration operation ([eb5aabb](https://github.com/dropseed/plain/commit/eb5aabb5ca))
- Added `BaseDatabaseSchemaEditor` and `StateModelsRegistry` exports from `plain.models.migrations` for use in type annotations in `RunPython` functions ([672aa88](https://github.com/dropseed/plain/commit/672aa8861a))

### Upgrade instructions

- Remove any `db_column` arguments from field definitions - the column name will always match the field's attribute name (with `_id` suffix for foreign keys)
- Remove `db_column` from all migrations
- Remove any `db_collation` arguments from `CharField` and `TextField` definitions
- Replace any usage of `Collate()` function with raw SQL queries or configure collation at the database level
- Remove any `db_comment` arguments from field definitions
- Remove `db_comment` from all migrations
- Remove any `db_table_comment` from `model_options` definitions
- Replace `AlterModelTableComment` migration operations with `RunSQL` if database comments are still needed

## [0.75.0](https://github.com/dropseed/plain/releases/plain-models@0.75.0) (2026-01-15)

### What's changed

- Added type annotations to `CursorWrapper` fetch methods (`fetchone`, `fetchmany`, `fetchall`) for better type checker support ([7635258](https://github.com/dropseed/plain/commit/7635258de0))
- Internal cleanup: removed redundant `tzinfo` class attribute from `TruncBase` ([0cb5a84](https://github.com/dropseed/plain/commit/0cb5a84718))

### Upgrade instructions

- No changes required

## [0.74.0](https://github.com/dropseed/plain/releases/plain-models@0.74.0) (2026-01-15)

### What's changed

- Internal skill configuration update - no user-facing changes ([fac8673](https://github.com/dropseed/plain/commit/fac8673436))

### Upgrade instructions

- No changes required

## [0.73.0](https://github.com/dropseed/plain/releases/plain-models@0.73.0) (2026-01-15)

### What's changed

- The `__repr__` method on models now returns `<ClassName: id>` instead of `<ClassName: str(self)>`, avoiding potential side effects from custom `__str__` implementations ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))

### Upgrade instructions

- No changes required

## [0.72.0](https://github.com/dropseed/plain/releases/plain-models@0.72.0) (2026-01-13)

### What's changed

- Fixed `TimezoneField` deconstruct path to correctly resolve to `plain.models` instead of `plain.models.fields.timezones`, preventing migration churn when using `TimezoneField` ([03cc263](https://github.com/dropseed/plain/commit/03cc263ffa))

### Upgrade instructions

- No changes required

## [0.71.0](https://github.com/dropseed/plain/releases/plain-models@0.71.0) (2026-01-13)

### What's changed

- `TimeZoneField` choices are no longer serialized in migrations, preventing spurious migration diffs when timezone data differs between machines ([0ede3aae](https://github.com/dropseed/plain/commit/0ede3aae5d))
- `TimeZoneField` no longer accepts custom choices - the field's purpose is to provide the canonical timezone list ([0ede3aae](https://github.com/dropseed/plain/commit/0ede3aae5d))
- Simplified `plain migrate` output - package name is only shown when explicitly targeting a specific package ([006efae9](https://github.com/dropseed/plain/commit/006efae92d))
- Field ordering is now explicit (primary key first, then alphabetically by name) instead of using an internal creation counter ([3ffa44bd](https://github.com/dropseed/plain/commit/3ffa44bdcb))

### Upgrade instructions

- If you have existing migrations that contain `TimeZoneField` with serialized `choices`, you can safely remove the `choices` parameter from those migrations as they are now computed dynamically
- If you were passing custom `choices` to `TimeZoneField`, this is no longer supported - use a regular `CharField` with choices instead

## [0.70.0](https://github.com/dropseed/plain/releases/plain-models@0.70.0) (2025-12-26)

### What's changed

- Added `TimeZoneField` for storing timezone information - stores timezone names as strings in the database but provides `zoneinfo.ZoneInfo` objects when accessed, similar to how `DateField` works with `datetime.date` ([b533189](https://github.com/dropseed/plain/commit/b533189576))
- Documentation improvements listing all available field types in the README ([11837ad](https://github.com/dropseed/plain/commit/11837ad2f2))

### Upgrade instructions

- No changes required

## [0.69.1](https://github.com/dropseed/plain/releases/plain-models@0.69.1) (2025-12-22)

### What's changed

- Internal type annotation improvements for better type checker compatibility ([539a706](https://github.com/dropseed/plain/commit/539a706760), [5c0e403](https://github.com/dropseed/plain/commit/5c0e403863))

### Upgrade instructions

- No changes required

## [0.69.0](https://github.com/dropseed/plain/releases/plain-models@0.69.0) (2025-12-12)

### What's changed

- The `queryset.all()` method now preserves the prefetch cache, fixing an issue where accessing prefetched related objects through `.all()` would trigger additional database queries instead of using the cached results ([8b899a8](https://github.com/dropseed/plain/commit/8b899a807a))

### Upgrade instructions

- No changes required

## [0.68.0](https://github.com/dropseed/plain/releases/plain-models@0.68.0) (2025-12-09)

### What's changed

- Database backups now store git metadata (branch and commit) and the `plain db backups list` command displays this information along with source and size in a table format ([287fa89f](https://github.com/dropseed/plain/commit/287fa89fb1))
- Added `--branch` option to `plain db backups list` to filter backups by git branch ([287fa89f](https://github.com/dropseed/plain/commit/287fa89fb1))
- `ReverseForeignKey` and `ReverseManyToMany` now support an optional second type parameter for custom QuerySet types, enabling type checkers to recognize custom QuerySet methods on reverse relations ([487c6195](https://github.com/dropseed/plain/commit/487c6195bf))
- Internal cleanup: removed legacy generic foreign key related code ([c9ca1b67](https://github.com/dropseed/plain/commit/c9ca1b670a))

### Upgrade instructions

- To get type checking for custom QuerySet methods on reverse relations, you can optionally add a second type parameter: `books: types.ReverseForeignKey[Book, BookQuerySet] = types.ReverseForeignKey(to="Book", field="author")`. This is optional and existing code without the second parameter continues to work.

## [0.67.0](https://github.com/dropseed/plain/releases/plain-models@0.67.0) (2025-12-05)

### What's changed

- Simplified Query/Compiler architecture by moving compiler selection from Query classes to DatabaseOperations ([1d1ae5a6](https://github.com/dropseed/plain/commit/1d1ae5a61f))
- The `raw()` method now accepts any `Sequence` for params (e.g., lists) instead of requiring tuples ([1d1ae5a6](https://github.com/dropseed/plain/commit/1d1ae5a61f))
- Internal type annotation improvements across database backends and SQL compiler modules ([bc02184d](https://github.com/dropseed/plain/commit/bc02184de7), [e068dcf2](https://github.com/dropseed/plain/commit/e068dcf201), [33fa09d6](https://github.com/dropseed/plain/commit/33fa09d66f))

### Upgrade instructions

- No changes required

## [0.66.0](https://github.com/dropseed/plain/releases/plain-models@0.66.0) (2025-12-05)

### What's changed

- Removed `union()`, `intersection()`, and `difference()` combinator methods from QuerySet - use raw SQL for set operations instead ([0bae6abd](https://github.com/dropseed/plain/commit/0bae6abd94))
- Removed `dates()` and `datetimes()` methods from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Removed `in_bulk()` method from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Removed `contains()` method from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Internal cleanup: removed unused database backend feature flags and operations (`autoinc_sql`, `allows_group_by_selected_pks_on_model`, `connection_persists_old_columns`, `implied_column_null`, `for_update_after_from`, `select_for_update_of_column`, `modify_insert_params`) ([defe5015](https://github.com/dropseed/plain/commit/defe5015e6), [7e62b635](https://github.com/dropseed/plain/commit/7e62b635ba), [30073da1](https://github.com/dropseed/plain/commit/30073da128))

### Upgrade instructions

- Replace any usage of `queryset.union(other_qs)`, `queryset.intersection(other_qs)`, or `queryset.difference(other_qs)` with raw SQL queries using `Model.query.raw()` or database cursors
- Replace `queryset.dates(field, kind)` with equivalent annotate/values_list queries using `Trunc` and `DateField`
- Replace `queryset.datetimes(field, kind)` with equivalent annotate/values_list queries using `Trunc` and `DateTimeField`
- Replace `queryset.in_bulk(id_list)` with a dictionary comprehension like `{obj.id: obj for obj in queryset.filter(id__in=id_list)}`
- Replace `queryset.contains(obj)` with `queryset.filter(id=obj.id).exists()`

## [0.65.1](https://github.com/dropseed/plain/releases/plain-models@0.65.1) (2025-12-04)

### What's changed

- Fixed type annotations for `get_rhs_op` method in lookup classes to accept `str | list[str]` parameter, resolving type checker errors when using `Range` and other lookups that return list-based RHS values ([7030cd0](https://github.com/dropseed/plain/commit/7030cd0ee0))

### Upgrade instructions

- No changes required

## [0.65.0](https://github.com/dropseed/plain/releases/plain-models@0.65.0) (2025-12-04)

### What's changed

- Improved type annotations for `ReverseForeignKey` and `ReverseManyToMany` descriptors - they are now proper generic descriptor classes with `__get__` overloads, providing better type inference when accessed on class vs instance ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))
- Internal type annotation improvements across aggregates, expressions, database backends, and SQL compiler modules ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.64.0](https://github.com/dropseed/plain/releases/plain-models@0.64.0) (2025-11-24)

### What's changed

- `bulk_create()` and `bulk_update()` now accept any `Sequence` type (e.g., tuples, generators) instead of requiring a `list` ([6c7469f](https://github.com/dropseed/plain/commit/6c7469f92a))

### Upgrade instructions

- No changes required

## [0.63.1](https://github.com/dropseed/plain/releases/plain-models@0.63.1) (2025-11-21)

### What's changed

- Fixed `ManyToManyField` preflight checks that could fail when the intermediate model contained non-related fields (e.g., `CharField`, `IntegerField`) by properly filtering to only check `RelatedField` instances when counting foreign keys ([4a3fe5d](https://github.com/dropseed/plain/commit/4a3fe5d530))

### Upgrade instructions

- No changes required

## [0.63.0](https://github.com/dropseed/plain/releases/plain-models@0.63.0) (2025-11-21)

### What's changed

- `ForeignKey` has been renamed to `ForeignKeyField` for consistency with other field naming conventions ([8010204](https://github.com/dropseed/plain/commit/8010204b36))
- Improved type annotations for `ManyToManyField` - now returns `ManyToManyManager[T]` instead of `Any` for better IDE support ([4536097](https://github.com/dropseed/plain/commit/4536097be1))
- Related managers (`ReverseForeignKeyManager` and `ManyToManyManager`) are now generic classes with proper type parameters for improved type checking ([3f61b6e](https://github.com/dropseed/plain/commit/3f61b6e51f))
- Added `ManyToManyManager` and `ReverseForeignKeyManager` exports to `plain.models.types` for use in type annotations ([4536097](https://github.com/dropseed/plain/commit/4536097be1))

### Upgrade instructions

- Replace all usage of `models.ForeignKey` with `models.ForeignKeyField` (e.g., `category = models.ForeignKey("Category", on_delete=models.CASCADE)` becomes `category = models.ForeignKeyField("Category", on_delete=models.CASCADE)`)
- Replace all usage of `types.ForeignKey` with `types.ForeignKeyField` in typed model definitions
- Update migrations to use `ForeignKeyField` instead of `ForeignKey`

## [0.62.1](https://github.com/dropseed/plain/releases/plain-models@0.62.1) (2025-11-20)

### What's changed

- Fixed a bug where non-related fields could cause errors in migrations and schema operations by incorrectly assuming all fields have a `remote_field` attribute ([60b1bcc](https://github.com/dropseed/plain/commit/60b1bcc1c5))

### Upgrade instructions

- No changes required

## [0.62.0](https://github.com/dropseed/plain/releases/plain-models@0.62.0) (2025-11-20)

### What's changed

- The `named` parameter has been removed from `QuerySet.values_list()` - named tuples are no longer supported for values lists ([0e39711](https://github.com/dropseed/plain/commit/0e397114c2))
- Internal method `get_extra_restriction()` has been removed from related fields and query data structures ([6157bd9](https://github.com/dropseed/plain/commit/6157bd90385137faf2cafbbd423a99326eedcd3b))
- Internal helper function `get_model_meta()` has been removed in favor of direct attribute access ([cb5a50e](https://github.com/dropseed/plain/commit/cb5a50ef1a0c5af61b97b96459bb14ed85df6f7f))
- Extensive type annotation improvements across the entire package, including database backends, query compilers, fields, migrations, and SQL modules ([a43145e](https://github.com/dropseed/plain/commit/a43145e69732a792b376e6548c6aac384df0ce28))
- Added `isinstance` checks for related fields and improved type narrowing throughout the codebase ([5b4bdf4](https://github.com/dropseed/plain/commit/5b4bdf47e74964780300e20c5fabfce68fa424c7))
- Improved type annotations for `Options.get_fields()` and related meta methods with more specific return types ([2c26f86](https://github.com/dropseed/plain/commit/2c26f86573df0cef473153d6224abdb99082e893))

### Upgrade instructions

- Remove any usage of the `named=True` parameter in `values_list()` calls - if you need named access to query results, use `.values()` which returns dictionaries instead

## [0.61.1](https://github.com/dropseed/plain/releases/plain-models@0.61.1) (2025-11-17)

### What's changed

- The `@dataclass_transform` decorator has been removed from `ModelBase` to avoid type checker issues ([e0dbedb](https://github.com/dropseed/plain/commit/e0dbedb73f))
- Documentation and examples no longer suggest using `ClassVar` for QuerySet type annotations - the simpler `query: models.QuerySet[Model] = models.QuerySet()` pattern is now recommended ([1c624ff](https://github.com/dropseed/plain/commit/1c624ff29e), [99aecbc](https://github.com/dropseed/plain/commit/99aecbc17e))

### Upgrade instructions

- If you were using `ClassVar` annotations for the `query` attribute, you can optionally remove the `ClassVar` wrapper and the `from typing import ClassVar` import. Both patterns work, but the simpler version without `ClassVar` is now recommended.

## [0.61.0](https://github.com/dropseed/plain/releases/plain-models@0.61.0) (2025-11-14)

### What's changed

- The `related_name` parameter has been removed from `ForeignKey` and `ManyToManyField` - reverse relationships are now declared explicitly using `ReverseForeignKey` and `ReverseManyToMany` descriptors on the related model ([a4b630969d](https://github.com/dropseed/plain/commit/a4b630969d))
- Added `ReverseForeignKey` and `ReverseManyToMany` descriptor classes to `plain.models.types` for declaring reverse relationships with full type support ([a4b630969d](https://github.com/dropseed/plain/commit/a4b630969d))
- The new reverse descriptors are exported from `plain.models` for easy access ([97fa112975](https://github.com/dropseed/plain/commit/97fa112975))
- Renamed internal references from `ManyToOne` to `ForeignKey` for consistency ([93c30f9caf](https://github.com/dropseed/plain/commit/93c30f9caf))
- Fixed a preflight check bug related to reverse relationships ([9191ae6e4b](https://github.com/dropseed/plain/commit/9191ae6e4b))
- Added comprehensive documentation for reverse relationships in the README ([5abf330e06](https://github.com/dropseed/plain/commit/5abf330e06))

### Upgrade instructions

- Remove all `related_name` parameters from `ForeignKey` and `ManyToManyField` definitions
- Remove `related_name` from all migrations
- On the related model, add explicit reverse relationship descriptors using `ReverseForeignKey` or `ReverseManyToMany` from `plain.models.types`:
    - For the reverse side of a `ForeignKey`, use: `children: types.ReverseForeignKey[Child] = types.ReverseForeignKey(to="Child", field="parent")`
    - For the reverse side of a `ManyToManyField`, use: `cars: types.ReverseManyToMany[Car] = types.ReverseManyToMany(to="Car", field="features")`
- Remove any `TYPE_CHECKING` blocks that were used to declare reverse relationship types - the new descriptors provide full type support without these hacks
- The `to` parameter accepts either a string (model name) or the model class itself
- The `field` parameter should be the name of the forward field on the related model

## [0.60.0](https://github.com/dropseed/plain/releases/plain-models@0.60.0) (2025-11-13)

### What's changed

- Type annotations for QuerySets using `ClassVar` to improve type checking when accessing `Model.query` ([c3b00a6](https://github.com/dropseed/plain/commit/c3b00a693c))
- The `id` field on the Model base class now uses a type annotation (`id: int = types.PrimaryKeyField()`) for better type checking ([9febc80](https://github.com/dropseed/plain/commit/9febc801f4))
- Replaced wildcard imports (`import *`) with explicit imports in internal modules for better code clarity ([eff36f3](https://github.com/dropseed/plain/commit/eff36f31e8))

### Upgrade instructions

- Optionally (but recommended) add `ClassVar` type annotations to custom QuerySets on your models using `query: ClassVar[models.QuerySet[YourModel]] = models.QuerySet()` for improved type checking and IDE autocomplete

## [0.59.1](https://github.com/dropseed/plain/releases/plain-models@0.59.1) (2025-11-13)

### What's changed

- Added documentation for typed field definitions in the README, showing examples of using `plain.models.types` with type annotations ([f95d32d](https://github.com/dropseed/plain/commit/f95d32df5a))

### Upgrade instructions

- Optionally (but recommended) move to typed model field definitions by using `name: str = types.CharField(...)` instead of `name = models.CharField(...)`. Types can be imported with `from plain.models import types`.

## [0.59.0](https://github.com/dropseed/plain/releases/plain-models@0.59.0) (2025-11-13)

### What's changed

- Added a new `plain.models.types` module with type stub support (.pyi) for improved IDE and type checker experience when defining models ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc75a))
- Added `@dataclass_transform` decorator to `ModelBase` to enable better type checking for model field definitions ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc75a))

### Upgrade instructions

- No changes required

## [0.58.0](https://github.com/dropseed/plain/releases/plain-models@0.58.0) (2025-11-12)

### What's changed

- Internal base classes have been converted to use Python's ABC (Abstract Base Class) module with `@abstractmethod` decorators, improving type checking and making the codebase more maintainable ([b1f40759](https://github.com/dropseed/plain/commit/b1f40759eb), [7146cabc](https://github.com/dropseed/plain/commit/7146cabc42), [74f9a171](https://github.com/dropseed/plain/commit/74f9a1717a), [b647d156](https://github.com/dropseed/plain/commit/b647d156ce), [6f3e35d9](https://github.com/dropseed/plain/commit/6f3e35d9b0), [95620673](https://github.com/dropseed/plain/commit/95620673d9), [7ff5e98c](https://github.com/dropseed/plain/commit/7ff5e98c6f), [78323300](https://github.com/dropseed/plain/commit/78323300df), [df82434d](https://github.com/dropseed/plain/commit/df82434d50), [16350d98](https://github.com/dropseed/plain/commit/16350d98b1), [066eaa4b](https://github.com/dropseed/plain/commit/066eaa4bd7), [60fabefa](https://github.com/dropseed/plain/commit/60fabefa77), [9f822ccc](https://github.com/dropseed/plain/commit/9f822cccc8), [6b31752c](https://github.com/dropseed/plain/commit/6b31752c95))
- Type annotations have been improved across database backends, query compilers, and migrations for better IDE support ([f4dbcefa](https://github.com/dropseed/plain/commit/f4dbcefa92), [dc182c2e](https://github.com/dropseed/plain/commit/dc182c2e51))

### Upgrade instructions

- No changes required

## [0.57.0](https://github.com/dropseed/plain/releases/plain-models@0.57.0) (2025-11-11)

### What's changed

- The `plain.models` import namespace has been cleaned up to only include the most commonly used APIs for defining models ([e9edf61](https://github.com/dropseed/plain/commit/e9edf61c6b), [22b798c](https://github.com/dropseed/plain/commit/22b798cf57), [d5a2167](https://github.com/dropseed/plain/commit/d5a2167d14))
- Field classes are now descriptors themselves, eliminating the need for a separate descriptor class ([93f8bd7](https://github.com/dropseed/plain/commit/93f8bd72e9))
- Model initialization no longer accepts positional arguments - all field values must be passed as keyword arguments ([685f99a](https://github.com/dropseed/plain/commit/685f99a33a))
- Attempting to set a primary key during model initialization now raises a clear `ValueError` instead of silently accepting the value ([ecf490c](https://github.com/dropseed/plain/commit/ecf490cb2a))

### Upgrade instructions

- Import advanced query features from their specific modules instead of `plain.models`:
    - Aggregates: `from plain.models.aggregates import Avg, Count, Max, Min, Sum`
    - Expressions: `from plain.models.expressions import Case, Exists, Expression, ExpressionWrapper, F, Func, OuterRef, Subquery, Value, When, Window`
    - Query utilities: `from plain.models.query import Prefetch, prefetch_related_objects`
    - Lookups: `from plain.models.lookups import Lookup, Transform`
- Remove any positional arguments in model instantiation and use keyword arguments instead (e.g., `User("John", "Doe")` becomes `User(first_name="John", last_name="Doe")`)

## [0.56.1](https://github.com/dropseed/plain/releases/plain-models@0.56.1) (2025-11-03)

### What's changed

- Fixed preflight checks and README to reference the correct new command names (`plain db shell` and `plain migrations prune`) instead of the old `plain models` commands ([b293750](https://github.com/dropseed/plain/commit/b293750f6f))

### Upgrade instructions

- No changes required

## [0.56.0](https://github.com/dropseed/plain/releases/plain-models@0.56.0) (2025-11-03)

### What's changed

- The CLI has been reorganized into separate `plain db` and `plain migrations` command groups for better organization ([7910a06](https://github.com/dropseed/plain/commit/7910a06e86132ef1fc1720bd960916ee009e27cf))
- The `plain models` command group has been removed - use `plain db` and `plain migrations` instead ([7910a06](https://github.com/dropseed/plain/commit/7910a06e86132ef1fc1720bd960916ee009e27cf))
- The `plain backups` command group has been removed - use `plain db backups` instead ([dd87b76](https://github.com/dropseed/plain/commit/dd87b762babb370751cffdc27be3c6a53c6c98b4))
- Database backup output has been simplified to show file size and timestamp on a single line ([765d118](https://github.com/dropseed/plain/commit/765d1184c6d0bdb1f91a85bf511d049da74a6276))

### Upgrade instructions

- Replace `plain models db-shell` with `plain db shell`
- Replace `plain models db-wait` with `plain db wait`
- Replace `plain models list` with `plain db list` (note: this command was moved to the main plain package)
- Replace `plain models show-migrations` with `plain migrations list`
- Replace `plain models prune-migrations` with `plain migrations prune`
- Replace `plain models squash-migrations` with `plain migrations squash`
- Replace `plain backups` commands with `plain db backups` (e.g., `plain backups list` becomes `plain db backups list`)
- The shortcuts `plain makemigrations` and `plain migrate` continue to work unchanged

## [0.55.1](https://github.com/dropseed/plain/releases/plain-models@0.55.1) (2025-10-31)

### What's changed

- Added `license = "BSD-3-Clause"` to package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355e65b62be6e4618bcc814c912e050dc388))

### Upgrade instructions

- No changes required

## [0.55.0](https://github.com/dropseed/plain/releases/plain-models@0.55.0) (2025-10-24)

### What's changed

- The plain-models package now uses an explicit `package_label = "plainmodels"` to avoid conflicts with other packages ([d1783dd](https://github.com/dropseed/plain/commit/d1783dd564cb48380e59cb4598722649a7d9574f))
- Fixed migration loader to correctly check for `plainmodels` package label instead of `models` ([c41d11c](https://github.com/dropseed/plain/commit/c41d11c70d02bab59c6951ef1074b13a392d04a6))

### Upgrade instructions

- No changes required

## [0.54.0](https://github.com/dropseed/plain/releases/plain-models@0.54.0) (2025-10-22)

### What's changed

- SQLite migrations are now always run separately instead of in atomic batches, fixing issues with foreign key constraint handling ([5082453](https://github.com/dropseed/plain/commit/508245375960f694cfac4e17a6bfbb2301969a5c))

### Upgrade instructions

- No changes required

## [0.53.1](https://github.com/dropseed/plain/releases/plain-models@0.53.1) (2025-10-20)

### What's changed

- Internal packaging update to use `dependency-groups` standard instead of `tool.uv.dev-dependencies` ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.53.0](https://github.com/dropseed/plain/releases/plain-models@0.53.0) (2025-10-12)

### What's changed

- Added new `plain models prune-migrations` command to identify and remove stale migration records from the database ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))
- The `--prune` option has been removed from `plain migrate` command in favor of the dedicated `prune-migrations` command ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))
- Added new preflight check `models.prunable_migrations` that warns about stale migration records in the database ([9b43617](https://github.com/dropseed/plain/commit/9b4361765c))
- The `show-migrations` command no longer displays prunable migrations in its output ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))

### Upgrade instructions

- Replace any usage of `plain migrate --prune` with the new `plain models prune-migrations` command

## [0.52.0](https://github.com/dropseed/plain/releases/plain-models@0.52.0) (2025-10-10)

### What's changed

- The `plain migrate` command now shows detailed operation descriptions and SQL statements for each migration step, replacing the previous verbosity levels with a cleaner `--quiet` flag ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))
- Migration output format has been improved to display each operation's description and the actual SQL being executed, making it easier to understand what changes are being made to the database ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))
- The `-v/--verbosity` option has been removed from `plain migrate` in favor of the simpler `--quiet` flag for suppressing output ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))

### Upgrade instructions

- Replace any usage of `-v` or `--verbosity` flags in `plain migrate` commands with `--quiet` if you want to suppress migration output

## [0.51.1](https://github.com/dropseed/plain/releases/plain-models@0.51.1) (2025-10-08)

### What's changed

- Fixed a bug in `Subquery` and `Exists` expressions that was using the old `query` attribute name instead of `sql_query` when extracting the SQL query from a QuerySet ([79ca52d](https://github.com/dropseed/plain/commit/79ca52d32e))

### Upgrade instructions

- No changes required

## [0.51.0](https://github.com/dropseed/plain/releases/plain-models@0.51.0) (2025-10-07)

### What's changed

- Model metadata has been split into two separate descriptors: `model_options` for user-defined configuration and `_model_meta` for internal metadata ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0), [17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- The `_meta` attribute has been replaced with `model_options` for user-defined options like indexes, constraints, and database settings ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- Custom QuerySets are now assigned directly to the `query` class attribute instead of using `Meta.queryset_class` ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Added comprehensive type improvements to model metadata and related fields for better IDE support ([3b477a0](https://github.com/dropseed/plain/commit/3b477a0d43))

### Upgrade instructions

- Replace `Meta.queryset_class = CustomQuerySet` with `query = CustomQuerySet()` as a class attribute on your models
- Replace `class Meta:` with `model_options = models.Options(...)` in your models

## [0.50.0](https://github.com/dropseed/plain/releases/plain-models@0.50.0) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout plain-models, improving IDE support and type checking capabilities ([ea1a7df](https://github.com/dropseed/plain/commit/ea1a7df622), [f49ee32](https://github.com/dropseed/plain/commit/f49ee32a90), [369353f](https://github.com/dropseed/plain/commit/369353f9d6), [13b7d16](https://github.com/dropseed/plain/commit/13b7d16f8d), [e23a0ca](https://github.com/dropseed/plain/commit/e23a0cae7c), [02d8551](https://github.com/dropseed/plain/commit/02d85518f0))
- The `QuerySet` class is now generic and the `model` parameter is now required in the `__init__` method ([719e792](https://github.com/dropseed/plain/commit/719e792c96))
- Database wrapper classes have been renamed for consistency: `DatabaseWrapper` classes are now named `MySQLDatabaseWrapper`, `PostgreSQLDatabaseWrapper`, and `SQLiteDatabaseWrapper` ([5a39e85](https://github.com/dropseed/plain/commit/5a39e851e5))
- The plain-models package now has 100% type annotation coverage and is validated in CI to prevent regressions

### Upgrade instructions

- No changes required

## [0.49.2](https://github.com/dropseed/plain/releases/plain-models@0.49.2) (2025-10-02)

### What's changed

- Updated dependency to use the latest plain package version

### Upgrade instructions

- No changes required

## [0.49.1](https://github.com/dropseed/plain/releases/plain-models@0.49.1) (2025-09-29)

### What's changed

- Fixed `get_field_display()` method to accept field name as string instead of field object ([1c20405](https://github.com/dropseed/plain/commit/1c20405ac3))

### Upgrade instructions

- No changes required

## [0.49.0](https://github.com/dropseed/plain/releases/plain-models@0.49.0) (2025-09-29)

### What's changed

- Model exceptions (`FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, `FullResultSet`) have been moved from `plain.exceptions` to `plain.models.exceptions` ([1c02564](https://github.com/dropseed/plain/commit/1c02564561))
- The `get_FOO_display()` methods for fields with choices have been replaced with a single `get_field_display(field_name)` method ([e796e71](https://github.com/dropseed/plain/commit/e796e71e02))
- The `get_next_by_*` and `get_previous_by_*` methods for date fields have been removed ([3a5b8a8](https://github.com/dropseed/plain/commit/3a5b8a89d1))
- The `id` primary key field is now defined directly on the Model base class instead of being added dynamically via Options ([e164dc7](https://github.com/dropseed/plain/commit/e164dc7982))
- Model `DoesNotExist` and `MultipleObjectsReturned` exceptions now use descriptors for better performance ([8f54ea3](https://github.com/dropseed/plain/commit/8f54ea3a62))

### Upgrade instructions

- Update imports for model exceptions from `plain.exceptions` to `plain.models.exceptions` (e.g., `from plain.exceptions import ObjectDoesNotExist` becomes `from plain.models.exceptions import ObjectDoesNotExist`)
- Replace any usage of `instance.get_FOO_display()` with `instance.get_field_display("FOO")` where FOO is the field name
- Remove any usage of `get_next_by_*` and `get_previous_by_*` methods - use QuerySet ordering instead (e.g., `Model.query.filter(date__gt=obj.date).order_by("date").first()`)

## [0.48.0](https://github.com/dropseed/plain/releases/plain-models@0.48.0) (2025-09-26)

### What's changed

- Migrations now run in a single transaction by default for databases that support transactional DDL, providing all-or-nothing migration batches for better safety and consistency ([6d0c105](https://github.com/dropseed/plain/commit/6d0c105fa9))
- Added `--atomic-batch/--no-atomic-batch` options to `plain migrate` to explicitly control whether migrations are run in a single transaction ([6d0c105](https://github.com/dropseed/plain/commit/6d0c105fa9))

### Upgrade instructions

- No changes required

## [0.47.0](https://github.com/dropseed/plain/releases/plain-models@0.47.0) (2025-09-25)

### What's changed

- The `QuerySet.query` property has been renamed to `QuerySet.sql_query` to better distinguish it from the `Model.query` manager interface ([d250eea](https://github.com/dropseed/plain/commit/d250eeac03))

### Upgrade instructions

- If you directly accessed the `QuerySet.query` property in your code (typically for advanced query manipulation or debugging), rename it to `QuerySet.sql_query`

## [0.46.1](https://github.com/dropseed/plain/releases/plain-models@0.46.1) (2025-09-25)

### What's changed

- Fixed `prefetch_related` for reverse foreign key relationships by correctly handling related managers in the prefetch query process ([2c04e80](https://github.com/dropseed/plain/commit/2c04e80dcd))

### Upgrade instructions

- No changes required

## [0.46.0](https://github.com/dropseed/plain/releases/plain-models@0.46.0) (2025-09-25)

### What's changed

- The preflight system has been completely reworked with a new `PreflightResult` class that unifies messages and hints into a single `fix` field, providing clearer and more actionable error messages ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461), [c7cde12](https://github.com/dropseed/plain/commit/c7cde12149))
- Preflight check IDs have been renamed to use descriptive names instead of numbers for better clarity (e.g., `models.E003` becomes `models.duplicate_many_to_many_relations`) ([cd96c97](https://github.com/dropseed/plain/commit/cd96c97b25))
- Removed deprecated field types: `CommaSeparatedIntegerField`, `IPAddressField`, and `NullBooleanField` ([345295dc](https://github.com/dropseed/plain/commit/345295dc8a))
- Removed `system_check_deprecated_details` and `system_check_removed_details` from fields ([e3a7d2dd](https://github.com/dropseed/plain/commit/e3a7d2dd10))

### Upgrade instructions

- Remove any usage of the deprecated field types `CommaSeparatedIntegerField`, `IPAddressField`, and `NullBooleanField` - use `CharField`, `GenericIPAddressField`, and `BooleanField(null=True)` respectively

## [0.45.0](https://github.com/dropseed/plain/releases/plain-models@0.45.0) (2025-09-21)

### What's changed

- Added unlimited varchar support to SQLite - CharField fields without a max_length now generate `varchar` columns instead of `varchar()` with no length specified ([c5c0c3a](https://github.com/dropseed/plain/commit/c5c0c3a743))

### Upgrade instructions

- No changes required

## [0.44.0](https://github.com/dropseed/plain/releases/plain-models@0.44.0) (2025-09-19)

### What's changed

- PostgreSQL backup restoration now drops and recreates the database instead of using `pg_restore --clean`, providing more reliable restoration by terminating active connections and ensuring a completely clean database state ([a8865fe](https://github.com/dropseed/plain/commit/a8865fe5d6))
- Added `_meta` type annotation to the `Model` class for improved type checking and IDE support ([387b92e](https://github.com/dropseed/plain/commit/387b92e08b))

### Upgrade instructions

- No changes required

## [0.43.0](https://github.com/dropseed/plain/releases/plain-models@0.43.0) (2025-09-12)

### What's changed

- The `related_name` parameter is now required for ForeignKey and ManyToManyField relationships if you want a reverse accessor. The `"+"` suffix to disable reverse relations has been removed, and automatic `_set` suffixes are no longer generated ([89fa03979f](https://github.com/dropseed/plain/commit/89fa03979f))
- Refactored related descriptors and managers for better internal organization and type safety ([9f0b03957a](https://github.com/dropseed/plain/commit/9f0b03957a))
- Added docstrings and return type annotations to model `query` property and related manager methods for improved developer experience ([544d85b60b](https://github.com/dropseed/plain/commit/544d85b60b))

### Upgrade instructions

- Remove any `related_name="+"` usage - if you don't want a reverse accessor, simply omit the `related_name` parameter entirely
- Update any code that relied on automatic `_set` suffixes - these are no longer generated, so you must use explicit `related_name` values
- Add explicit `related_name` arguments to all ForeignKey and ManyToManyField definitions where you want reverse access (e.g., `models.ForeignKey(User, on_delete=models.CASCADE, related_name="articles")`)
- Consider removing `related_name` arguments that are not used in practice

## [0.42.0](https://github.com/dropseed/plain/releases/plain-models@0.42.0) (2025-09-12)

### What's changed

- The model manager interface has been renamed from `.objects` to `.query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Manager functionality has been merged into QuerySet, simplifying the architecture - custom QuerySets can now be set directly via `Meta.queryset_class` ([bbaee93](https://github.com/dropseed/plain/commit/bbaee93839))
- The `objects` manager is now set directly on the Model class for better type checking ([fccc5be](https://github.com/dropseed/plain/commit/fccc5be13e))
- Database backups are now created automatically during migrations when in DEBUG mode ([c8023074](https://github.com/dropseed/plain/commit/c8023074e9))
- Removed several legacy manager features: `default_related_name`, `base_manager_name`, `creation_counter`, `use_in_migrations`, `auto_created`, and routing hints ([multiple commits](https://github.com/dropseed/plain/compare/plain-models@0.41.1...037a239ef4))

### Upgrade instructions

- Replace all usage of `Model.objects` with `Model.query` in your codebase (e.g., `User.objects.filter()` becomes `User.query.filter()`)
- If you have custom managers, convert them to custom QuerySets and set them using `Meta.queryset_class` instead of assigning to class attributes (if there is more than one custom manager on a class, invoke the new QuerySet class directly or add a shortcut on the Model using `@classmethod`)
- Remove any usage of the removed manager features: `default_related_name`, `base_manager_name`, manager `creation_counter`, `use_in_migrations`, `auto_created`, and database routing hints
- Any reverse accessors (typically `<related_model>_set` or defined by `related_name`) will now return a manager class for the additional `add()`, `remove()`, `clear()`, etc. methods and the regular queryset methods will be available via `.query` (e.g., `user.articles.first()` becomes `user.articles.query.first()`)

## [0.41.1](https://github.com/dropseed/plain/releases/plain-models@0.41.1) (2025-09-09)

### What's changed

- Improved stack trace filtering in OpenTelemetry spans to exclude internal plain/models frames, making debugging traces cleaner and more focused on user code ([5771dd5](https://github.com/dropseed/plain/commit/5771dd5))

### Upgrade instructions

- No changes required

## [0.41.0](https://github.com/dropseed/plain/releases/plain-models@0.41.0) (2025-09-09)

### What's changed

- Python 3.13 is now the minimum required version ([d86e307](https://github.com/dropseed/plain/commit/d86e307))
- Removed the `earliest()`, `latest()`, and `get_latest_by` model meta option - use `order_by().first()` and `order_by().last()` instead ([b6093a8](https://github.com/dropseed/plain/commit/b6093a8))
- Removed automatic ordering in `first()` and `last()` queryset methods - they now respect the existing queryset ordering without adding default ordering ([adc19a6](https://github.com/dropseed/plain/commit/adc19a6))
- Added code location attributes to database operation tracing, showing the source file, line number, and function where the query originated ([da36a17](https://github.com/dropseed/plain/commit/da36a17))

### Upgrade instructions

- Replace usage of `earliest()`, `latest()`, and model `Meta` `get_latest_by` queryset methods with equivalent `order_by().first()` or `order_by().last()` calls
- The `first()` and `last()` methods no longer automatically add ordering by `id` - explicitly add `.order_by()` to your querysets or `ordering` to your models `Meta` class if needed

## [0.40.1](https://github.com/dropseed/plain/releases/plain-models@0.40.1) (2025-09-03)

### What's changed

- Internal documentation updates for agent commands ([df3edbf0bd](https://github.com/dropseed/plain/commit/df3edbf0bd))

### Upgrade instructions

- No changes required

## [0.40.0](https://github.com/dropseed/plain/releases/plain-models@0.40.0) (2025-08-05)

### What's changed

- Foreign key fields now accept lazy objects (like `SimpleLazyObject` used for `request.user`) by automatically evaluating them ([eb78dcc76d](https://github.com/dropseed/plain/commit/eb78dcc76d))
- Added `--no-input` option to `plain migrate` command to skip user prompts ([0bdaf0409e](https://github.com/dropseed/plain/commit/0bdaf0409e))
- Removed the `plain models optimize-migration` command ([6e4131ab29](https://github.com/dropseed/plain/commit/6e4131ab29))
- Removed the `--fake-initial` option from `plain migrate` command ([6506a8bfb9](https://github.com/dropseed/plain/commit/6506a8bfb9))
- Fixed CLI help text to reference `plain` commands instead of `manage.py` ([8071854d61](https://github.com/dropseed/plain/commit/8071854d61))

### Upgrade instructions

- Remove any usage of `plain models optimize-migration` command - it is no longer available
- Remove any usage of `--fake-initial` option from `plain migrate` commands - it is no longer supported
- It is no longer necessary to do `user=request.user or None`, for example, when setting foreign key fields with a lazy object like `request.user`. These will now be automatically evaluated.

## [0.39.2](https://github.com/dropseed/plain/releases/plain-models@0.39.2) (2025-07-25)

### What's changed

- Fixed remaining `to_field_name` attribute usage in `ModelMultipleChoiceField` validation to use `id` directly ([26c80356d3](https://github.com/dropseed/plain/commit/26c80356d3))

### Upgrade instructions

- No changes required

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
