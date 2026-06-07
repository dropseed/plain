# plain-cache changelog

## [0.29.0](https://github.com/dropseed/plain/releases/plain-cache@0.29.0) (2026-06-07)

### What's changed

- **`plain.cache` is redesigned around a stateless, module-level `cache` singleton.** The `Cached(key)` class is gone; import `cache` and pass the key per call. ([ab0f4b876f](https://github.com/dropseed/plain/commit/ab0f4b876f))

    | Before                              | After                              |
    | ----------------------------------- | ---------------------------------- |
    | `Cached("k").set(v, expiration=60)` | `cache.set("k", v, expiration=60)` |
    | `Cached("k").value`                 | `cache.get("k")`                   |
    | `Cached("k").exists()`              | `cache.exists("k")`                |
    | `Cached("k").delete()`              | `cache.delete("k")`                |

- **`get()` replaces the `.value` property** and takes an optional default — `cache.get("k", default)` returns the default on a miss or expiry (instead of always `None`).
- **`set()` is now `cache.set(key, value, *, expiration=...)`** — `expiration` is keyword-only, and `set()` returns `None` (it previously returned the stored value). It still rewrites the whole entry, including its expiry.
- **New `get_or_set(key, default, *, expiration=None)`** — returns the cached value, or computes/stores/returns it on a miss. `default` may be a value or a zero-arg callable (invoked only on a miss). A stored `None` counts as a hit.
- **New batch methods** — `get_many(keys)` (a single query, returns only live entries), `set_many(mapping, *, expiration=None)`, and `delete_many(keys)`.
- **New `touch(key, *, expiration=None)`** — change a live entry's expiration _without_ rewriting its value. It writes only `expires_at`/`updated_at`, reusing the existing TOAST pointer, so refreshing the TTL of a multi-megabyte value doesn't re-TOAST the blob. Returns `True` if a live entry was updated, `False` for a missing/expired key. Ideal for sliding-TTL caches of large values.
- **New `clear()`** — delete every entry; returns the number of rows deleted. (`delete()` returns a bool; `delete_many()` and `clear()` return counts.)
- **New `CachedItem.query.live()` queryset method** — the never-expiring-or-not-yet-expired filter that reads now use, so an entry past its `expires_at` reads as absent. `expired()`/`unexpired()`/`forever()` are unchanged; note `unexpired()` still matches only rows with a _future_ expiry (excluding forever rows), whereas `live()` includes them.
- **Stricter `expiration` validation** — a `bool` or a bare `date` passed as `expiration` now raises `TypeError` instead of being silently treated as "never expires."

### Upgrade instructions

- Replace `Cached("key")` with the `cache` singleton (see the table above): `from plain.cache import cache`, then `cache.get("key")` / `cache.set("key", value, expiration=...)` / `cache.exists("key")` / `cache.delete("key")`.
- `expiration` is now keyword-only on `set()` — use `cache.set("k", v, expiration=60)`, not a positional third argument.
- If you read `Cached(...).value`, switch to `cache.get(key)` (pass a default if you don't want `None`).
- If you relied on `set()` returning the stored value, note it now returns `None`.
- No migration required — the `CachedItem` model is unchanged.

## [0.28.2](https://github.com/dropseed/plain/releases/plain-cache@0.28.2) (2026-06-03)

### What's changed

- A raced unique-key conflict during `set()` now surfaces as a `ValidationError` (mapped at the save boundary in `plain.postgres`), so the retry path catches `(psycopg.IntegrityError, ValidationError)` rather than `IntegrityError` alone. ([40c97521c5](https://github.com/dropseed/plain/commit/40c97521c5))

### Upgrade instructions

- No changes required. Requires `plain.postgres>=0.106.0`.

## [0.28.1](https://github.com/dropseed/plain/releases/plain-cache@0.28.1) (2026-05-25)

### What's changed

- Internal: model field declarations updated for plain.postgres's new parameterized-descriptor field typing. ([229ecdbbfa](https://github.com/dropseed/plain/commit/229ecdbbfa))

### Upgrade instructions

- No changes required.

## [0.28.0](https://github.com/dropseed/plain/releases/plain-cache@0.28.0) (2026-05-06)

### What's changed

- Tighter autovacuum on `plaincache_cacheditem` by default. The cache table is a high-churn workload — every `set()` rewrites a row, and TOAST'd values leave orphaned chunks behind — so Plain now declares per-table storage parameters via the new `plain-postgres` `storage_parameters` API: `autovacuum_vacuum_scale_factor=0.1` (heap) and `toast.autovacuum_vacuum_scale_factor=0.05` (TOAST), down from Postgres' default of `0.2`. Both are exposed as the new `CACHE_AUTOVACUUM_SCALE_FACTOR` and `CACHE_TOAST_AUTOVACUUM_SCALE_FACTOR` settings (overridable via `PLAIN_CACHE_*` env vars). Convergence applies them on the next `plain postgres sync`. ([7fe40f72](https://github.com/dropseed/plain/commit/7fe40f72))

### Upgrade instructions

- Requires `plain-postgres>=0.103.0`. Run `plain postgres sync` after upgrading to apply the new autovacuum storage parameters to `plaincache_cacheditem`.

## [0.27.5](https://github.com/dropseed/plain/releases/plain-cache@0.27.5) (2026-05-05)

### What's changed

- Exposes `__version__` from `importlib.metadata` on `plain.cache` for version probes that don't want to scrape pip metadata. ([c6cf6edb](https://github.com/dropseed/plain/commit/c6cf6edb))

### Upgrade instructions

- No changes required.

## [0.27.4](https://github.com/dropseed/plain/releases/plain-cache@0.27.4) (2026-04-17)

### What's changed

- Updated `CachedItem.created_at` and `CachedItem.updated_at` to the new `create_now` / `update_now` kwargs for plain-postgres 0.96.0. ([5d145e4](https://github.com/dropseed/plain/commit/5d145e4), [a44e5ec](https://github.com/dropseed/plain/commit/a44e5ec))

### Upgrade instructions

- Requires `plain-postgres>=0.96.0`. Run `plain postgres sync` after upgrading to reconcile column defaults.

## [0.27.3](https://github.com/dropseed/plain/releases/plain-cache@0.27.3) (2026-04-14)

### What's changed

- Updated `clear-expired` and `clear-all` CLI commands and the `ClearExpired` chore to use the new `QuerySet.delete()` return type (an `int` directly instead of a `(count, by_label)` tuple) from plain-postgres 0.95.0. ([29e10dba51d9](https://github.com/dropseed/plain/commit/29e10dba51d9))
- Added explicit `plain.postgres>=0.95.0` dependency — the package has always imported `plain.postgres` APIs but previously relied on it being present transitively.

### Upgrade instructions

- Requires `plain-postgres>=0.95.0`.

## [0.27.2](https://github.com/dropseed/plain/releases/plain-cache@0.27.2) (2026-04-05)

### What's changed

- **Removed OTel span instrumentation from cache operations.** Cache operations (`get`, `set`, `delete`, `exists`) no longer create their own OTel spans. The underlying postgres queries already produce `db.*` spans automatically, making the cache-level spans redundant noise. ([b56a9edc9c7d](https://github.com/dropseed/plain/commit/b56a9edc9c7d))

### Upgrade instructions

- No changes required.

## [0.27.1](https://github.com/dropseed/plain/releases/plain-cache@0.27.1) (2026-03-29)

### What's changed

- Removed `AddIndex` and `RenameIndex` operations from migrations — indexes are now managed by convergence. ([c58b4ba1fec9](https://github.com/dropseed/plain/commit/c58b4ba1fec9))
- Updated docs to reference `plain postgres sync` instead of `plain migrate`. ([b026895edc4c](https://github.com/dropseed/plain/commit/b026895edc4c))

### Upgrade instructions

- No changes required.

## [0.27.0](https://github.com/dropseed/plain/releases/plain-cache@0.27.0) (2026-03-28)

### What's changed

- Replaced `CharField` with `TextField` in models and migration files to match plain-postgres 0.90.0 ([5062ee4dd1fd](https://github.com/dropseed/plain/commit/5062ee4dd1fd))

### Upgrade instructions

- Requires `plain-postgres>=0.90.0`
- Replace `CharField` with `TextField` in migration files that reference this package's models

## [0.26.3](https://github.com/dropseed/plain/releases/plain-cache@0.26.3) (2026-03-27)

### What's changed

- Changed `cache clear-all` confirmation flag from `--force` to `--yes`/`-y` for consistency across all CLI commands ([0af36e101f03](https://github.com/dropseed/plain/commit/0af36e101f03))

### Upgrade instructions

- If you use `plain cache clear-all --force` in scripts, change it to `plain cache clear-all --yes`.

## [0.26.2](https://github.com/dropseed/plain/releases/plain-cache@0.26.2) (2026-03-25)

### What's changed

- Renamed indexes to use readable `{table}_{column}_idx` naming convention, replacing the old truncated hash-based names. Includes a migration with `RenameIndex` operations (instant `ALTER INDEX RENAME`, no locks). ([74aa8b76aa40](https://github.com/dropseed/plain/commit/74aa8b76aa40))

### Upgrade instructions

- Run `plain migrate` to apply the index rename migration. This is an instant metadata-only operation with no performance impact.

## [0.26.1](https://github.com/dropseed/plain/releases/plain-cache@0.26.1) (2026-03-22)

### What's changed

- Switched from `plain.postgres.IntegrityError` to `psycopg.IntegrityError` directly ([d4b170e60a2c](https://github.com/dropseed/plain/commit/d4b170e60a2c))

### Upgrade instructions

- No changes required.

## [0.26.0](https://github.com/dropseed/plain/releases/plain-cache@0.26.0) (2026-03-12)

### What's changed

- Updated all imports from `plain.models` to `plain.postgres` in admin, core, models, and migrations.

### Upgrade instructions

- Update imports: `from plain.models` to `from plain.postgres`, `from plain import models` to `from plain import postgres`.

## [0.25.4](https://github.com/dropseed/plain/releases/plain-cache@0.25.4) (2026-02-26)

### What's changed

- Removed redundant `allow_global_search = False` from cache admin views — this is now the default in plain-admin ([05d6fa2764](https://github.com/dropseed/plain/commit/05d6fa2764))

### Upgrade instructions

- No changes required.

## [0.25.3](https://github.com/dropseed/plain/releases/plain-cache@0.25.3) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.25.2](https://github.com/dropseed/plain/releases/plain-cache@0.25.2) (2026-02-04)

### What's changed

- Added `__all__` exports to `models` module for explicit public API boundaries ([f26a63a5c941](https://github.com/dropseed/plain/commit/f26a63a5c941))

### Upgrade instructions

- No changes required.

## [0.25.1](https://github.com/dropseed/plain/releases/plain-cache@0.25.1) (2026-01-28)

### What's changed

- Updated admin views to use the new `get_initial_queryset` hook instead of `get_objects` ([99d6f042b8](https://github.com/dropseed/plain/commit/99d6f042b8))

### Upgrade instructions

- If you have customized the cache admin views, rename `get_objects()` to `get_initial_queryset()`.

## [0.25.0](https://github.com/dropseed/plain/releases/plain-cache@0.25.0) (2026-01-15)

### What's changed

- Admin interface updated with new "database" icon and added description for cached items list view ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-cache@0.24.0) (2026-01-13)

### What's changed

- Expanded README documentation with comprehensive usage examples, FAQs, and improved structure ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

## [0.23.0](https://github.com/dropseed/plain/releases/plain-cache@0.23.0) (2025-11-24)

### What's changed

- Removed unused type ignore comment for improved code cleanliness ([bfb851f](https://github.com/dropseed/plain/commit/bfb851f9b5))

### Upgrade instructions

- No changes required

## [0.22.1](https://github.com/dropseed/plain/releases/plain-cache@0.22.1) (2025-11-17)

### What's changed

- QuerySet manager type annotation updated from `ClassVar` to standard annotation for improved type checker compatibility ([1c624ff](https://github.com/dropseed/plain/commit/1c624ff29e))

### Upgrade instructions

- No changes required

## [0.22.0](https://github.com/dropseed/plain/releases/plain-cache@0.22.0) (2025-11-13)

### What's changed

- QuerySet manager now uses `ClassVar` type annotation for improved type checking ([c3b00a6](https://github.com/dropseed/plain/commit/c3b00a693c))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-cache@0.21.0) (2025-11-13)

### What's changed

- Model field definitions now use type stub syntax with `plain.models.types` for improved type checking and IDE support ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc75a))

### Upgrade instructions

- No changes required

## [0.20.2](https://github.com/dropseed/plain/releases/plain-cache@0.20.2) (2025-11-03)

### What's changed

- CLI commands now include descriptive docstrings for improved help text ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80103))

### Upgrade instructions

- No changes required

## [0.20.1](https://github.com/dropseed/plain/releases/plain-cache@0.20.1) (2025-10-31)

### What's changed

- Added BSD-3-Clause license metadata to package configuration ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-cache@0.20.0) (2025-10-17)

### What's changed

- Chores have been rewritten as abstract base classes instead of function-based decorators ([c4466d3](https://github.com/dropseed/plain/commit/c4466d3c60))

### Upgrade instructions

- If you have custom chores defined, update them from function-based decorators to class-based chores that inherit from `Chore` and implement a `run()` method (see [plain.chores documentation](https://github.com/dropseed/plain/tree/master/plain/plain/chores))

## [0.19.0](https://github.com/dropseed/plain/releases/plain-cache@0.19.0) (2025-10-07)

### What's changed

- Model configuration updated from `class Meta` to `model_options` descriptor for improved type safety ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- QuerySet is now a proper descriptor with enhanced type annotations ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Improved type safety by removing `type: ignore` comments throughout the package ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.18.1](https://github.com/dropseed/plain/releases/plain-cache@0.18.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package, achieving 100% type coverage ([154d4c4](https://github.com/dropseed/plain/commit/154d4c44fc))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-cache@0.18.0) (2025-09-12)

### What's changed

- Model manager API has been updated from `.objects` to `.query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version requirement raised to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Update any custom code that references `CachedItem.objects` to use `CachedItem.query` instead

## [0.17.2](https://github.com/dropseed/plain/releases/plain-cache@0.17.2) (2025-08-22)

### What's changed

- Updated README.md with improved documentation structure and formatting ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Admin interface icon positioning updated to be on nav sections ([5a6479a](https://github.com/dropseed/plain/commit/5a6479ac79))

### Upgrade instructions

- No changes required

## [0.17.1](https://github.com/dropseed/plain/releases/plain-cache@0.17.1) (2025-07-23)

### What's changed

- Added archive icon to the cache admin interface navigation ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-cache@0.17.0) (2025-07-22)

### What's changed

- Database migrations updated to use new PrimaryKeyField instead of BigAutoField ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Admin interface now uses `id` instead of `pk` for queryset ordering

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-cache@0.16.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support for all cache operations (get, set, delete, exists) ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-cache@0.15.0) (2025-07-18)

### What's changed

- Database migrations have been restarted and consolidated into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93))
- Admin interface query optimization restored using `.only()` to fetch minimal fields for list views

### Upgrade instructions

- Run `plain migrate --prune plaincache` to handle the migration restart and remove old migration files

## [0.14.3](https://github.com/dropseed/plain/releases/plain-cache@0.14.3) (2025-06-26)

### What's changed

- No user-facing changes. This release only adds and formats the package CHANGELOG file (82710c3).

### Upgrade instructions

- No changes required
