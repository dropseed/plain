---
related:
  - postgres-native-orm
  - models-db-level-on-delete
  - postgres-cli-and-insights
---

# Postgres-native schema

Plain's model layer can't represent a lot of what Postgres can do at the table level. The query API has reasonable coverage (lookups, aggregation, window functions), but the schema definition layer — what you can express in a model class — has gaps that force users to drop to `RunSQL` migrations or raw DDL.

This is a different problem from the query API. You can always drop to `sql()` for queries. You can't drop to "raw DDL" for schema definitions without abandoning the migration autodetector entirely.

## Philosophy

The schema layer should be able to express any Postgres table feature that the migration system can then generate DDL for. If Postgres supports it as a column type, constraint, or index type, you should be able to declare it on a model and get migrations for free.

This doesn't mean wrapping every Postgres feature in Python convenience — it means letting people _define_ a Postgres-native schema that migrations can manage.

## Gaps

### 1. Generated columns

Postgres supports `GENERATED ALWAYS AS (expression) STORED` — a column whose value is automatically derived from other columns, maintained by the database on every insert/update.

**Why it matters:**

- Full-text search vectors (`to_tsvector('english', title)`) kept in sync without triggers
- Fallback values (`COALESCE(dark_id, light_id)`) without application logic
- Derived data (domain extraction from email, unit conversions) always consistent
- Functional indexes can sometimes be replaced by a generated column + regular index, which is simpler to reason about

**What Plain needs:**

A way to declare a generated column on a model. The migration system needs to emit `GENERATED ALWAYS AS (expression) STORED`. The field should be read-only in the ORM (no writes, no inclusion in INSERT/UPDATE).

```python
class Product(models.Model):
    price_cents = IntegerField()
    price_dollars = GeneratedField(
        expression="price_cents / 100.0",
        output_field=DecimalField(),
    )
```

Open questions:

- Should `expression` be a string (raw SQL) or an Expression object? Raw SQL is simpler and more honest — generated column expressions are inherently SQL. Expression objects add complexity for the autodetector but enable column reference validation.
- How does `ALTER TABLE ... ADD COLUMN ... GENERATED` interact with existing data? Postgres computes the value for all existing rows, which could be slow on large tables.
- Should the field appear in `Model._meta.fields`? It should be selectable but not writable.

### 2. GIN and GiST index types

Plain only supports B-tree indexes. Postgres has several index types optimized for different access patterns:

| Index type | Use case                                        | Plain support |
| ---------- | ----------------------------------------------- | ------------- |
| B-tree     | Equality, range, sorting                        | Yes           |
| GIN        | Containment, existence (JSONB, arrays, FTS)     | **No**        |
| GiST       | Geometric, range overlap, exclusion constraints | **No**        |
| Hash       | Strict equality only, constant size             | **No**        |
| SP-GiST    | Partitioned search trees                        | **No**        |
| BRIN       | Large naturally-ordered tables                  | **No**        |

GIN and GiST are the highest value to add:

**GIN** is needed for:

- JSONB `@>` containment queries (JSONField already supports these lookups but can't create proper indexes)
- Full-text search (`tsvector` columns)
- Array containment queries
- `jsonb_path_ops` operator class for smaller, faster containment-only indexes

**GiST** is needed for:

- Exclusion constraints (range non-overlap)
- Range containment queries
- Geometric/spatial data

**Implementation:** The `Index` class needs a `type` parameter or we need separate classes (`GinIndex`, `GistIndex`). Django contrib.postgres uses separate classes. A `type` parameter is simpler:

```python
class Meta:
    indexes = [
        Index(fields=["search_vector"], type="gin"),
        Index(fields=["data"], type="gin", opclasses=["jsonb_path_ops"]),
    ]
```

Hash indexes are a lower priority — B-tree covers most equality cases. BRIN and SP-GiST are niche.

### 3. Exclusion constraints

Exclusion constraints prevent rows from conflicting based on operator-defined criteria. They're uniquely powerful for ensuring non-overlapping ranges — something check constraints and unique constraints can't do.

**Real-world use cases:**

- Hotel/meeting room reservations (no overlapping time ranges per room)
- Employee schedules (no overlapping shifts per employee)
- IP address allocation (no overlapping CIDR ranges)
- Event scheduling with cancellation support (partial exclusion with WHERE predicate)

**What Plain needs:**

An `ExclusionConstraint` class alongside `CheckConstraint` and `UniqueConstraint`:

```python
class Reservation(models.Model):
    room_id = IntegerField()
    period = DateTimeRangeField()
    status = TextField()

    class Meta:
        constraints = [
            ExclusionConstraint(
                name="no_overlapping_reservations",
                expressions=[
                    ("room_id", "="),
                    ("period", "&&"),
                ],
                index_type="gist",
                condition=Q(status__ne="canceled"),  # partial exclusion
            ),
        ]
```

Requires:

- GiST index support (see above)
- The `btree_gist` extension for using equality operators in GiST (needed when mixing `=` with `&&`). Could auto-detect and suggest `CREATE EXTENSION btree_gist` in preflight.

### 4. Range fields

Postgres range types are "meta types" that wrap subtypes with powerful operators for containment, overlap, and adjacency:

| Type        | Wraps                | Example                                  |
| ----------- | -------------------- | ---------------------------------------- |
| `int4range` | integer              | `[1, 10)`                                |
| `int8range` | bigint               | `[1, 1000000)`                           |
| `numrange`  | numeric              | `[1.5, 8.3]`                             |
| `daterange` | date                 | `[2024-01-01, 2024-12-31]`               |
| `tsrange`   | timestamp without tz | `[2024-01-01 00:00, 2024-01-02 00:00)`   |
| `tstzrange` | timestamptz          | `[2024-01-01T00:00Z, 2024-01-02T00:00Z)` |

**Lookups needed:**

- `contains` (`@>`) — range contains value or range
- `contained_by` (`<@`) — range is within another range
- `overlap` (`&&`) — ranges share points
- `adjacent_to` (`-|-`) — ranges are adjacent
- `startswith`, `endswith` — bound access
- `isempty` — empty range check

**Bounds syntax:** `[]` inclusive, `()` exclusive. Postgres normalizes discrete ranges (e.g., integer `[1, 5]` becomes `[1, 6)`).

Range fields pair with exclusion constraints for the booking/scheduling use cases above.

psycopg3 has native `Range` types that map directly, so the Python ↔ Postgres conversion is straightforward.

### 5. Array fields

Postgres arrays store ordered lists of a single type with containment and overlap operators:

```python
class Article(models.Model):
    tags = ArrayField(base_field=TextField())
```

**Lookups needed:**

- `contains` (`@>`) — array contains elements
- `contained_by` (`<@`) — array is subset
- `overlap` (`&&`) — arrays share elements
- `len` — array length
- Index access (e.g., `tags__0` for first element)

**Trade-offs vs. M2M:**

- Arrays: simpler schema, no join table, good for small fixed lists (tags, categories). No referential integrity.
- M2M: referential integrity, queryable from both sides, better for large/shared value sets.

Arrays need GIN indexes for efficient containment queries.

### 6. Hash indexes (low priority)

Strict equality only, constant compact size regardless of input. Good for long URLs, API tokens, large text values where only exact match is needed. Safe since Postgres 10+ (crash-safe, WAL-replicated).

B-tree covers most equality cases, so this is low priority. But it's trivial to add as `type="hash"` on the Index class.

### 7. Fillfactor as a model option

Postgres `fillfactor` controls how full table pages are packed (default 100%). Lowering it to 70-80% leaves room for HOT (Heap-Only Tuple) updates — in-place updates that skip index maintenance entirely when no indexed column changes.

This is a significant performance lever for write-heavy models (e.g., models with frequently updated `status` or `updated_at` columns). Most frameworks completely ignore it.

```python
class Job(models.Model):
    status = TextField()
    updated_at = DateTimeField()

    model_options = postgres.Options(
        fillfactor=80,  # leave 20% of each page for HOT updates
    )
```

Generates: `ALTER TABLE jobs SET (fillfactor = 80);`

Guidelines:

- **100%** (default): Insert-only or read-mostly tables
- **70-80%**: Write-heavy tables with frequent updates to non-indexed columns
- **Never index frequently-updated columns** (`status`, `updated_at`) unless query-critical — it defeats HOT
- Monitor via `n_tup_hot_upd / n_tup_upd` ratio in `pg_stat_user_tables` (target >90%)

### 8. Table partitioning (future)

Postgres supports declarative table partitioning for managing very large tables. Partitioning benefits maintenance (vacuum, index builds) and data retention more than pure query speed.

Thresholds for considering partitioning:

- General tables: >100GB or >20M rows
- Time-series / logs / events: >50GB or >10M rows

Two common strategies:

- **Range partitioning**: By timestamp (most common) — one partition per month/week
- **List partitioning**: By tenant, region, or category

This would require:

- Model-level partition declaration (partition key, strategy)
- Migration support for `PARTITION BY RANGE/LIST`
- Partition creation/detachment operations
- Constraint: partition key MUST be part of primary key and unique constraints

This is a larger effort and probably belongs in its own exploration when a concrete use case drives it. The key decision is whether Plain should manage partition lifecycle (creating new monthly partitions, detaching old ones) or leave that to tools like `pg_partman`.

## What this enables

With these schema features in place:

- **Full-text search** becomes possible without raw SQL migrations (generated column for tsvector + GIN index)
- **Booking/scheduling systems** get database-level integrity (range fields + exclusion constraints)
- **JSONB gets proper indexing** (GIN indexes on existing JSONField)
- **Tag systems** can skip join tables for simple cases (array fields + GIN)
- **The `postgres-native-orm` sql() layer** becomes more powerful because the schema it operates on is richer

## Implementation priority

The priority is driven by dependency chains. Items 1–3 form a chain that culminates in full-text search being declarable entirely through model code — the showcase feature for the postgres-first thesis.

| Priority | Feature               | Effort | Unlocks                                           | Depends on              |
| -------- | --------------------- | ------ | ------------------------------------------------- | ----------------------- |
| 1        | GIN/GiST index types  | Small  | JSONB indexing, FTS indexing, array indexing      | —                       |
| 2        | Generated columns     | Medium | FTS vectors, derived data, COALESCE patterns      | —                       |
| 3        | Exclusion constraints | Medium | Non-overlapping ranges, scheduling integrity      | GiST (1)                |
| 4        | Array fields          | Medium | Tags without join tables, GIN-indexed containment | GIN (1)                 |
| 5        | Range fields          | Medium | Temporal data, pairing with exclusion constraints | GiST (1), exclusion (3) |
| 6        | Fillfactor            | Small  | HOT update optimization for write-heavy tables    | —                       |

GIN/GiST indexes are the highest leverage — they're small to implement and immediately unlock proper indexing for an existing field type (JSONField) while unblocking most other features on this list. Generated columns are independent but together with GIN they enable FTS (`postgres-full-text-search`).

### Convergence integration

Each feature added here expands the set of **managed types** in convergence (see `schema-convergence.md` "Ownership" section). Today, convergence only manages B-tree indexes and unique/check/FK constraints. When GIN support ships, GIN becomes a managed index type — convergence creates, tracks, and can drop GIN indexes declared on models. Until then, GIN indexes in the database are shown as **unmanaged** in `postgres schema` and are invisible to convergence operations.

## What we won't build

Not every Postgres feature needs a model-level declaration. The goal is covering features where dropping to `RunSQL` forces users out of the migration autodetector entirely. Features where the escape hatch composes cleanly with the managed layer don't need wrapping.

### Not planned

| Feature                           | Why not                                                                                                                                                                                                                                                                        |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Hash indexes**                  | B-tree covers nearly all equality cases. The marginal benefit (constant-size for very long keys) doesn't justify the surface area. Trivial to add later as `type="hash"` if demand emerges.                                                                                    |
| **BRIN indexes**                  | Niche — useful for large naturally-ordered tables (time-series). Create via `RunSQL`; convergence won't touch them (unmanaged type).                                                                                                                                           |
| **SP-GiST indexes**               | Very niche (partitioned search trees). Same story as BRIN.                                                                                                                                                                                                                     |
| **Table partitioning**            | Large effort, complex lifecycle (partition creation, detachment, pruning). Better handled by `pg_partman` or manual DDL. The key question — should Plain manage partition lifecycle or delegate — doesn't have a clear answer without a concrete use case driving it.          |
| **Triggers**                      | Convergence manages declarative state, not procedural logic. A trigger is behavior, not schema. `RunSQL` or explicit migration is the right tool. Exception: if `on_update=Now()` lands (see `fields-db-defaults.md`), convergence could manage that specific trigger pattern. |
| **Views / materialized views**    | Out of scope for the model layer. Views are queries, not tables.                                                                                                                                                                                                               |
| **Row-level security policies**   | Niche and deeply tied to Postgres roles/permissions, which Plain doesn't manage.                                                                                                                                                                                               |
| **Custom types / domains**        | Low demand. Users needing these are already comfortable with raw DDL.                                                                                                                                                                                                          |
| **`db_collation` / `db_comment`** | Nice-to-have metadata. Not load-bearing for any other feature. Can be added incrementally if demand warrants.                                                                                                                                                                  |

### How the escape hatches compose

For features we don't wrap, users have two paths:

1. **`RunSQL` in migrations** — for one-time DDL (creating a partition scheme, adding a BRIN index, installing an extension). The object exists in the database alongside model-managed objects.

2. **`sql()` in queries** — for query-side features that don't have ORM wrappers (window functions, CTEs, LATERAL joins). Returns typed model instances.

Both compose cleanly with the managed layer:

- Objects created via `RunSQL` on model-managed tables are visible in `postgres schema` as **unmanaged** (labeled with their type), not flagged as issues. They coexist safely with convergence.
- `sql()` queries can reference model fields and return model instances, so dropping to SQL for a query doesn't mean abandoning the ORM for everything else.

The boundary is: if you're defining something convergence can declare, use a model declaration. If convergence can't declare it, use `RunSQL` / `sql()` and convergence will leave it alone.
