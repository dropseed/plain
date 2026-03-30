# Flat timestamped migrations

## Problem

The current per-app migration system creates complexity:

- Per-app directories with sequential numbering
- Cross-app dependency declarations
- Merge migrations when two developers create migrations simultaneously
- Migration graph that must be resolved on every migrate run
- The `app` column in `plain_migrations` that ties migrations to app labels

With slim migrations (no index/constraint ops) and convergence (handling cross-app FK coordination), the dependency graph has almost nothing left to coordinate.

## Solution

One flat list of timestamped migrations. No per-app directories. No dependency graph.

### Directory structure

```
app/
  migrations/
    20240101_120000_create_users.py           ← schema (auto-generated, has operations)
    20240115_093000_add_email.py              ← schema (auto-generated, has operations)
    20240201_140000_create_orders.py          ← schema (auto-generated, has operations)
    20240215_100000_backfill_status.py        ← data (developer-written, has run())
```

Package migrations live in the package and get discovered:

```
plain/sessions/migrations/20230601_000000_create_sessions.py
plain/auth/migrations/20230501_000000_create_users.py
```

The runner collects all migrations from all sources, sorts by timestamp, runs in order.

### Tracking table

```sql
CREATE TABLE plain_migrations (
    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    timestamp varchar NOT NULL UNIQUE,
    name varchar NOT NULL,
    source varchar NOT NULL,  -- package name or 'app'
    applied_at timestamptz NOT NULL DEFAULT now()
);
```

### Naming and timestamp format

**Decision: `YYYYMMDD_HHMMSS` (14-digit, to the second). Detect collisions at generation time and bump the second.**

Format: `{timestamp}_{description}.py`

Examples:

- `20240101_120000_create_users.py`
- `20240115_093000_add_email_to_users.py`
- `20240201_140000_backfill_status.py`

The timestamp is the migration's identity and sort key. The description is for humans -- auto-generated from the operation (e.g., `create_users`, `add_email_to_users`) or user-provided via `--name`.

No more sequential numbers. No more 0001_initial. No merge migrations.

### Timestamp collision handling

**Decision: bump the second on collision. No random suffixes, no microseconds.**

When `migrations create` generates a new migration:

1. Generate the timestamp from the current UTC time: `YYYYMMDD_HHMMSS`
2. Scan all existing migration files (across all sources) for timestamps
3. If the timestamp already exists, increment the second by 1
4. If that also exists, keep incrementing (degenerate case: 59 migrations in the same second)

```python
def next_available_timestamp() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    existing = {m.timestamp for m in discover_all_migrations()}
    while timestamp in existing:
        # Parse, add 1 second, re-format
        dt = datetime.datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
        dt += datetime.timedelta(seconds=1)
        timestamp = dt.strftime("%Y%m%d_%H%M%S")
    return timestamp
```

This is simple, deterministic, and preserves the fixed-width format. The bumped timestamp doesn't match wall-clock time exactly, but that's fine -- the timestamp is an ordering key, not a historical record. `applied_at` in the tracking table records when the migration actually ran.

#### Why not microseconds?

Microseconds (`YYYYMMDD_HHMMSS_ffffff`) would virtually eliminate collisions but:

- Makes timestamps 21 characters instead of 15 -- noisier filenames
- Loses the human-readable "these were created around the same time" signal
- Makes it harder to type/reference timestamps in commands
- Doesn't actually solve the problem -- two developers on different machines can still collide, and the collision check is needed regardless

#### Why not random suffixes?

Random suffixes (`20240101_120000_a3f2`) break determinism. Running `migrations create` twice in the same state should produce the same file. Random suffixes also make the ordering within a second arbitrary, when the natural "first one created gets the second, next one gets second+1" is more intuitive.

### What about ordering guarantees?

Within a project: timestamps are sequential as you create them. You can't add a field to a table before you create it -- the CreateModel has an earlier timestamp.

Across packages: package migrations have earlier timestamps (created when the package was built). User migrations come later.

Across packages — ordering is correct by design: a newly-released package migration may have an older timestamp than your project migrations. This is intentional. Package migrations set up tables that project code depends on. A package migration with timestamp `20240101_000000` running before your `20260301_000000` project migration is the right order, regardless of when the package was released.

Edge case — RunPython that queries another package's model: a simple `after = "20230501_000000"` attribute on the migration class (in `.py` files) or SQL comment (in `.sql` files), checked at apply time. Not a full graph, just a single "must come after" pointer. Rarely needed.

If the referenced timestamp doesn't exist (package uninstalled, file deleted), `postgres sync` fails with a hard error: "migration X declares after=Y which doesn't exist." If you declare a dependency, it must be satisfiable. Remove the `after` attribute if the referenced migration is gone.

## Industry comparison of timestamp/naming conventions

| Framework  | Format                                     | Collision handling  | Notes                                                                                                                                                                                                                                                                                                              |
| ---------- | ------------------------------------------ | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Rails**  | `YYYYMMDDHHMMSS` (14 digits, no separator) | None built-in       | Collisions are rare enough that Rails doesn't address them. If two developers create migrations with the same timestamp, they get duplicate version numbers. `schema_migrations` uses the timestamp as the version -- duplicates would fail on insert. In practice, developers notice during code review or merge. |
| **Prisma** | `YYYYMMDDHHMMSS` (directory name)          | None built-in       | Each migration is a directory containing `migration.sql`. Same collision risk as Rails, same "fix it at merge time" approach.                                                                                                                                                                                      |
| **Atlas**  | `YYYYMMDDHHMMSS` (file prefix)             | Configurable format | Default is `{{ now }}_{{ name }}.sql`. The format is customizable via `atlas.hcl`. No automatic collision detection.                                                                                                                                                                                               |
| **Django** | `0001`, `0002`, ... (sequential per app)   | Merge migrations    | Sequential numbering within each app. When two developers both create `0003_`, Django detects the conflict on the next `makemigrations` run and generates a merge migration (`0004_merge_...`). The merge migration system is the most complex collision-handling approach and the one we're eliminating.          |
| **Ecto**   | Developer-chosen names                     | N/A                 | Ecto migrations have a `@moduledoc` timestamp but the filename is developer-chosen. No auto-generation, no collision concern from tooling.                                                                                                                                                                         |
| **Flyway** | `V{version}__` (version prefix)            | Manual              | Version is typically sequential (`V1`, `V2`) or timestamp-based. Developer's responsibility to avoid collisions.                                                                                                                                                                                                   |

### What we learn

Every timestamp-based tool uses the same `YYYYMMDDHHMMSS` format (to the second). None of them use microseconds. Collisions are universally considered rare enough to handle at generation time rather than baking microsecond precision into every filename.

Rails and Prisma punt on collision handling entirely -- they rely on the uniqueness constraint in the tracking table to surface conflicts at migration time. This is fine for small teams but produces confusing errors in CI when two PRs happen to generate migrations in the same second.

Plain's approach (detect and bump at generation time) is slightly better: it prevents the collision before the file is written, so the developer never sees a confusing duplicate-version error.

## What this eliminates

- Per-app migration directories
- Sequential numbering and naming conventions
- The dependency graph and resolver
- Merge migrations
- The `app` column in the tracking table
- `enforce-0001-initial-naming` future -- no numbering at all
- `migrations-rename-app-column` future -- no app column

## Tracking table transition

Existing projects have the current tracking table with an `app` column and sequential migration names. The new table has `timestamp`, `name`, `source`, and no `app` column.

This is a bootstrapping problem — you can't use the migration system to migrate the migration system. The framework upgrade handles it directly: when `postgres sync` detects the old table format (checks for the `app` column), it migrates the tracking table in-place before running any migrations. This is a one-time framework-level migration, not a user migration.

The conversion maps old records to the new format:

- `app` → `source`
- Sequential name (`0003_add_fields`) → extract or synthesize a timestamp
- Old records are preserved for auditability

## Remaining considerations

- `migrations create` needs to detect which model changes haven't been captured yet, without per-app state tracking. With Option A (DB introspection), this is the model-vs-DB diff with a drift check.
- Package migrations need a convention for where they live within the package directory structure.
