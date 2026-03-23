---
labels:
  - plain-postgres
related:
  - postgres-native-schema
  - postgres-full-text-search
depends_on:
  - models-explicit-create-update
  - models-psycopg3-features
  - models-typed-query-api
---

# Postgres-native ORM

Plain is Postgres-only (`requires-python = ">=3.13"`, single backend). The ORM still carries Django's multi-database abstractions — methods that do multiple round-trips, throw away data Postgres would happily return, paper over race conditions with retry loops, and use naming that obscures the SQL being generated. We should map closer to what Postgres actually does.

## Philosophy

**Two layers: typed ORM for the 80%, safe SQL for the 20%.**

The ORM handles common queries — filtering, ordering, column selection, CRUD, upserts, eager loading, simple aggregation. These should be fully typed, use SQL-aligned naming, and be impossible to get wrong at the string level.

For everything else — joins across multiple tables, subqueries, window functions, CTEs, LATERAL joins, complex GROUP BY, UNION — drop to SQL. But not "raw SQL" in the Django sense (a scary escape hatch that returns untyped tuples). The SQL layer should be:

1. **Safe** — model-aware interpolation, parameterized values, no string formatting
2. **Typed** — you declare what you're getting back, and the return is typed Python objects
3. **Model-aware** — `{User.email}` resolves to column names, `{User.*}` includes field processing (decryption, type coercion)

The explicit boundary: if you're querying a single table with filters, ordering, and column selection, use the ORM. The moment you need a JOIN you didn't define as a FK, a subquery, a window function, or anything that would require inventing a Python wrapper for SQL syntax — write SQL. No `Subquery(OuterRef(...))`. No `Case(When(...))`. No Python-to-SQL translation layer for things SQL already says clearly.

This means we can **remove** a lot of surface area (F expressions, Q objects, Subquery, OuterRef, Exists, Case/When, extra()) and replace it with a smaller, better-typed API that's honest about the boundary between Python and SQL.

### Design principles

1. **Postgres gives data back from writes. Stop throwing it away.** Every INSERT, UPDATE, and DELETE supports RETURNING. We use it internally for PKs but hide it from users.
2. **Name things after what they do in SQL.** `where()` not `filter()`, `join()` not `select_related()`. When a developer reads the code, the SQL should be obvious.
3. **Expose Postgres as infrastructure.** Advisory locks replace Redis/ZK for coordination. LISTEN/NOTIFY replaces message brokers. Per-transaction isolation replaces application-level locking hacks.
4. **The ORM is for single-table operations. SQL is for multi-table operations.** Don't build Python wrappers for SQL syntax. Let SQL be SQL.

---

## API overview

### Before / after at a glance

#### Reads

| Operation                  | Before (current)                             | After (proposed)                                                                          | Notes                                                                |
| -------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Filter**                 | `qs.filter(email__startswith="foo")`         | `qs.where(User.email.startswith("foo"))`                                                  | SQL `WHERE`, typed field methods                                     |
| **Exclude**                | `qs.exclude(role="admin")`                   | `qs.where(~User.role.eq("admin"))`                                                        | Negation via `~`, no separate method                                 |
| **OR conditions**          | `qs.filter(Q(a=1) \| Q(b=2))`                | `qs.where(User.a.eq(1) \| User.b.eq(2))`                                                  | Composable conditions, no Q import                                   |
| **Order**                  | `qs.order_by("-created_at")`                 | `qs.order_by(User.created_at.desc())`                                                     | Typed, no magic string prefix                                        |
| **Select columns**         | `qs.values("id", "email")`                   | `qs.select(User.id, User.email)`                                                          | Maps to SQL SELECT clause                                            |
| **Select columns (flat)**  | `qs.values_list("email", flat=True)`         | `qs.select(User.email, flat=True)`                                                        | Same method, flat option                                             |
| **Computed columns**       | `qs.annotate(total=Sum("amount"))`           | `qs.select(User.id, total=Sum(Order.amount))`                                             | Annotations fold into select                                         |
| **Defer columns**          | `qs.defer("bio")` / `qs.only("id", "email")` | `qs.select(User.id, User.email)`                                                          | `select()` replaces both defer and only                              |
| **Eager-load FK**          | `qs.select_related("profile")`               | `qs.join("profile")`                                                                      | Maps to SQL JOIN                                                     |
| **Eager-load reverse/M2N** | `qs.prefetch_related("posts")`               | `qs.prefetch("posts")`                                                                    | Shorter, same semantics                                              |
| **Lock rows**              | `qs.select_for_update()`                     | `qs.for_update()`                                                                         | Shorter; add `for_share()`, `for_no_key_update()`, `for_key_share()` |
| **Complex queries**        | `qs.annotate(Subquery(OuterRef(...)))`       | `User.query.sql("SELECT ...")`                                                            | SQL for complex queries, not Python wrappers                         |
| **Raw SQL**                | `qs.raw("SELECT ...")` / `qs.extra(...)`     | `User.query.sql("SELECT {User.*} FROM {User} WHERE {User.email} = {email}", email="foo")` | Model-aware interpolation                                            |

#### Writes

| Operation              | Before (current)                            | After (proposed)                                                              | Queries | Notes                                      |
| ---------------------- | ------------------------------------------- | ----------------------------------------------------------------------------- | ------- | ------------------------------------------ |
| **Insert**             | `Model.query.create(**kw)`                  | _(unchanged)_                                                                 | 1       | Already uses RETURNING for PK              |
| **Upsert (single)**    | `update_or_create()` + IntegrityError retry | `qs.upsert(unique_fields=[...], **kw)`                                        | **1**   | `INSERT ON CONFLICT DO UPDATE RETURNING *` |
| **Upsert (bulk)**      | `bulk_create(update_conflicts=True, ...)`   | `qs.bulk_upsert(objs, update_fields=[...], unique_fields=[...])`              | 1       | Clearer name                               |
| **Upsert (counter)**   | Raw SQL                                     | `qs.upsert(conflict_defaults={"count": F("count") + Excluded("count")}, ...)` | **1**   | Atomic increment via `Excluded()`          |
| **Get or create**      | `get_or_create(defaults={...}, **kw)`       | _(keep, optimize internals)_                                                  | 1-2     | Read-first, never modifies existing        |
| **Instance insert**    | `obj.save()` (ambiguous)                    | `obj.create()`                                                                | 1       | See models-explicit-create-update          |
| **Instance update**    | `obj.save()` (ambiguous)                    | `obj.persist()`                                                               | 1       | See models-explicit-create-update          |
| **Bulk update**        | `qs.update(**kw)` → int                     | `qs.update(**kw)` → int                                                       | 1       | Same, but add `.returning()`               |
| **Update + get rows**  | `qs.update()` then second SELECT            | `qs.update(**kw).returning()`                                                 | **1**   | `UPDATE ... RETURNING *`                   |
| **Delete**             | `qs.delete()` → (count, details)            | `qs.delete()` → count                                                         | 1       | Simplify return value                      |
| **Delete + get rows**  | Not possible, data gone                     | `qs.delete().returning("id", "payload")`                                      | **1**   | `DELETE ... RETURNING cols`                |
| **Delete (fast)**      | `Model.query.all().delete()` (row-by-row)   | `truncate(Model, cascade=True)`                                               | **1**   | `TRUNCATE` vs Python cascade collector     |
| **Bulk insert (huge)** | `bulk_create()` (VALUES, parameter limit)   | `qs.copy_from(rows)`                                                          | 1       | Postgres COPY protocol                     |

#### Infrastructure

| Operation                 | Before (current)             | After (proposed)                                             | Notes                               |
| ------------------------- | ---------------------------- | ------------------------------------------------------------ | ----------------------------------- |
| **App-level lock**        | Raw SQL `pg_advisory_lock()` | `with advisory_lock("name"):`                                | Context manager, string keys hashed |
| **Transaction isolation** | Connection-level config only | `transaction.atomic(isolation="serializable")`               | Per-transaction                     |
| **Read-only transaction** | Not available                | `transaction.atomic(read_only=True)`                         | Optimizer hint                      |
| **Pub/sub**               | Raw SQL                      | `notify("channel", payload)` / `listen("channel", callback)` | Replaces external broker            |

### What to deprecate

| Current                              | Replacement                          | Why                                                          |
| ------------------------------------ | ------------------------------------ | ------------------------------------------------------------ |
| `filter()` / `exclude()`             | `where()`                            | SQL naming, one method replaces two                          |
| `update_or_create()`                 | `upsert()`                           | Two queries, race-prone                                      |
| `select_related()`                   | `join()`                             | SQL naming                                                   |
| `prefetch_related()`                 | `prefetch()`                         | Shorter, same thing                                          |
| `select_for_update()`                | `for_update()`                       | Shorter; add lock mode siblings                              |
| `values()` / `values_list()`         | `select()`                           | SQL naming, one method replaces two                          |
| `annotate()`                         | `select()` / `sql()`                 | Computed columns fold into select; complex aggregation → SQL |
| `defer()` / `only()`                 | `select()`                           | Column selection is one concept                              |
| `extra()` / `raw()`                  | `sql()`                              | Model-aware SQL with interpolation                           |
| `bulk_create(update_conflicts=True)` | `bulk_upsert()`                      | Clearer intent                                               |
| `Q()` objects                        | Field conditions with `\|` and `~`   | Type-safe, no import needed                                  |
| `F()` expressions                    | Field references (`Model.field + 1`) | Type-safe                                                    |
| `Subquery` / `OuterRef` / `Exists`   | `sql()`                              | SQL for complex queries, not Python wrappers                 |

---

## Detailed design

### 1. where() — filtering

`filter()` and `exclude()` are Django names for SQL `WHERE`. Two methods for one concept, with inverted logic. Replace with `where()`.

```python
# Current
User.query.filter(is_active=True, email__contains="@example.com").exclude(role="admin")

# Proposed
User.query.where(
    User.is_active.eq(True),
    User.email.contains("@example.com"),
    ~User.role.eq("admin"),
)
```

Multiple arguments are ANDed. OR via `|` on conditions. NOT via `~`. No `Q()` import needed.

Field methods replace double-underscore lookups:

| Current lookup                    | Proposed field method          |
| --------------------------------- | ------------------------------ |
| `filter(email="foo")`             | `User.email.eq("foo")`         |
| `filter(email__startswith="foo")` | `User.email.startswith("foo")` |
| `filter(age__gte=18)`             | `User.age.gte(18)`             |
| `filter(email__in=[...])`         | `User.email.is_in([...])`      |
| `filter(bio__isnull=True)`        | `User.bio.is_null()`           |
| `exclude(role="admin")`           | `~User.role.eq("admin")`       |

Type-safe: `User.email.gte(18)` is a type error (string field, int argument). Typos like `User.emial` are `AttributeError` at runtime and flagged by type checkers. See models-typed-query-api for the full field method surface.

### 2. select() — column selection

`values()`, `values_list()`, `annotate()`, `defer()`, and `only()` are five methods for variations of "which columns to SELECT." Consolidate into `select()`.

```python
# Current: five different methods for column selection
User.query.values("id", "email")                              # → list of dicts
User.query.values_list("email", flat=True)                     # → list of scalars
User.query.annotate(order_count=Count("orders"))               # → add computed column
User.query.only("id", "email")                                 # → model instances, only these loaded
User.query.defer("bio")                                        # → model instances, skip this column

# Proposed: one method
User.query.select(User.id, User.email)                         # → list of dicts (partial columns)
User.query.select(User.email, flat=True)                       # → list of scalars
User.query.select(User.id, order_count=Count("orders"))        # → add computed column
```

When `select()` is called, the return type changes from model instances to dicts/tuples (like `values()` today). For deferred loading on model instances, `select()` specifies which fields to load:

```python
# Load only id and email on the model instance
User.query.select(User.id, User.email).get(id=1)  # → User instance with only id, email loaded
```

Open question: should `select()` return dicts or model instances? Two modes, or always one? The typed-query-api proposal has more thinking on this.

### 3. join() and prefetch() — eager loading

```python
# Current
User.query.select_related("profile", "profile__company")
User.query.prefetch_related("posts", Prefetch("posts", queryset=Post.query.where(...)))

# Proposed
User.query.join("profile", "profile__company")
User.query.prefetch("posts", Prefetch("posts", queryset=Post.query.where(...)))
```

`join()` maps to SQL JOIN (LEFT JOIN for nullable FKs, INNER JOIN for non-nullable). `prefetch()` maps to a separate SELECT with `WHERE id IN (...)`. Same semantics, shorter names.

### 4. for_update() and lock mode variants

Postgres has four row lock modes. We only expose `FOR UPDATE` (the most restrictive).

| Method                | SQL                 | Blocks                | Use case                                          |
| --------------------- | ------------------- | --------------------- | ------------------------------------------------- |
| `for_update()`        | `FOR UPDATE`        | All other locks       | Exclusive row modification                        |
| `for_no_key_update()` | `FOR NO KEY UPDATE` | UPDATE, SHARE         | Modify non-key columns without blocking FK checks |
| `for_share()`         | `FOR SHARE`         | UPDATE, NO KEY UPDATE | Read lock, prevent modifications                  |
| `for_key_share()`     | `FOR KEY SHARE`     | UPDATE only           | Prevent PK/unique changes, allow non-key updates  |

```python
user = User.query.for_update().get(id=1)             # exclusive
user = User.query.for_no_key_update().get(id=1)       # less restrictive — doesn't block FK checks
user = User.query.for_share().get(id=1)                # read lock
user = User.query.for_key_share().get(id=1)            # lightest lock
```

All support `nowait=True`, `skip_locked=True`, and `of=(...)`.

### 5. sql() — the typed SQL layer

Replace `raw()`, `extra()`, and the Python expression wrappers (`Subquery`, `OuterRef`, `Exists`, `Case/When`, `F`, `Value`) with a single model-aware SQL method that is **safe** (parameterized, no string formatting), **typed** (you declare the return shape), and **model-aware** (field processing like encryption/coercion applied automatically).

This is the 20% layer — it should feel like a first-class feature, not an escape hatch.

#### Basic usage

```python
# Current: Python wrappers that obscure the SQL
from plain.postgres.expressions import Subquery, OuterRef, F, Value, Case, When

User.query.annotate(
    latest_order=Subquery(
        Order.query.filter(user=OuterRef("pk")).order_by("-created_at").values("total")[:1]
    ),
    tier=Case(
        When(order_count__gt=100, then=Value("gold")),
        When(order_count__gt=10, then=Value("silver")),
        default=Value("bronze"),
    ),
)

# Proposed: just write SQL
User.query.sql("""
    SELECT {User.*},
        (SELECT total FROM {Order} WHERE {Order.user_id} = {User.id}
         ORDER BY {Order.created_at} DESC LIMIT 1) AS latest_order,
        CASE
            WHEN order_count > 100 THEN 'gold'
            WHEN order_count > 10  THEN 'silver'
            ELSE 'bronze'
        END AS tier
    FROM {User}
""")
```

#### Interpolation

Two kinds of `{}` references, distinguished by whether they refer to a model or a parameter:

| Syntax         | Resolves to                       | Example                                                |
| -------------- | --------------------------------- | ------------------------------------------------------ |
| `{User}`       | Table name                        | `FROM {User}` → `FROM users`                           |
| `{User.*}`     | All columns with field processing | `SELECT {User.*}` → `SELECT id, email, ...`            |
| `{User.email}` | Column name                       | `WHERE {User.email} = ...` → `WHERE users.email = ...` |
| `{email}`      | Parameterized value (`$1`)        | `WHERE email = {email}` → `WHERE email = $1`           |

Model references (`{User}`, `{User.email}`) are resolved at query build time — they produce safe identifiers, not string interpolation. Parameter references (`{email}`) become parameterized values that go through the corresponding field's `get_db_prep_value` (so encrypted fields encrypt, date fields format, etc.).

**No string formatting.** `{email}` is not `f"{email}"`. It's a parameterized query placeholder. SQL injection is impossible.

#### Typed results

The key question for the SQL layer: what Python type do you get back?

**Option A: Model instances when possible**

```python
# {User.*} → returns User instances
users = User.query.sql("""
    SELECT {User.*} FROM {User}
    WHERE {User.email} LIKE {pattern}
""", pattern="%@example.com")
# type: list[User]
```

When the SELECT matches `{Model.*}`, the result is hydrated model instances — same as a regular ORM query. Field processing (decryption, type coercion) happens automatically.

**Option B: Typed result class for custom projections**

```python
# For custom projections, declare the return type
@dataclass
class UserStats:
    email: str
    order_count: int
    total_spent: Decimal

stats = User.query.sql("""
    SELECT {User.email}, count({Order.id}) AS order_count, sum({Order.total}) AS total_spent
    FROM {User}
    LEFT JOIN {Order} ON {Order.user_id} = {User.id}
    GROUP BY {User.id}
""", result_type=UserStats)
# type: list[UserStats]
```

With `result_type`, you get typed Python objects — not raw tuples or untyped dicts. The dataclass fields are matched to SQL column aliases by name.

**Option C: Plain dicts (simplest)**

```python
results = User.query.sql("SELECT {User.id}, {User.email} FROM {User}")
# type: list[dict[str, Any]]
```

Could support all three — model instances when `{Model.*}` is used, typed dataclasses when `result_type` is provided, dicts as fallback.

#### What this replaces

| Current                               | Proposed                                  | Why                        |
| ------------------------------------- | ----------------------------------------- | -------------------------- |
| `qs.raw("SELECT ...")`                | `Model.query.sql("SELECT {Model.*} ...")` | Model-aware, parameterized |
| `qs.extra(select={...}, where=[...])` | `Model.query.sql(...)`                    | Not a half-measure         |
| `Subquery(OuterRef(...))`             | Subquery in SQL                           | SQL is clearer             |
| `Case(When(...))`                     | CASE/WHEN in SQL                          | SQL is clearer             |
| `F("field") + Value(1)`               | `field + 1` in SQL                        | SQL is clearer             |
| `Exists(qs)`                          | `EXISTS (SELECT ...)` in SQL              | SQL is clearer             |

The Python expression system is the worst of both worlds: not type-safe AND harder to read than the SQL it's hiding. It exists because Django needed to generate SQL for multiple backends. We have one backend. Let SQL be SQL.

#### What stays in the ORM (the 80%)

These are common enough and type-safe enough to warrant ORM methods:

| ORM method                           | SQL it generates                       | Why keep it                      |
| ------------------------------------ | -------------------------------------- | -------------------------------- |
| `where(User.email.eq("foo"))`        | `WHERE email = $1`                     | Type-safe, most common operation |
| `order_by(User.created_at.desc())`   | `ORDER BY created_at DESC`             | Type-safe, very common           |
| `select(User.id, User.email)`        | `SELECT id, email`                     | Type-safe column selection       |
| `join("profile")`                    | `LEFT JOIN profiles ON ...`            | FK traversal, very common        |
| `.count()` / `.exists()`             | `SELECT COUNT(*)` / `SELECT 1 LIMIT 1` | Trivial, universal               |
| `create()` / `update()` / `delete()` | INSERT / UPDATE / DELETE               | CRUD is the core job             |
| `upsert()`                           | `INSERT ON CONFLICT DO UPDATE`         | Common, hard to get right in SQL |

The boundary: **single-table operations with typed fields stay in the ORM. Multi-table operations and anything that would require inventing Python syntax for SQL concepts goes to `sql()`.**

### 6. Upsert

Single atomic `INSERT ... ON CONFLICT DO UPDATE SET ... RETURNING *`. Replaces race-prone `update_or_create()`.

```python
item = CachedItem.query.upsert(
    key="my-key",
    defaults={"value": data, "expires_at": tomorrow},
    unique_fields=["key"],
)
```

```sql
INSERT INTO cached_items (key, value, expires_at) VALUES ('my-key', '...', '2026-03-13')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at
RETURNING *
```

With separate create/conflict data:

```python
item = CachedItem.query.upsert(
    key="my-key",
    defaults={"value": data},
    create_defaults={"value": data, "source": "initial"},  # insert-only
    unique_fields=["key"],
)
```

With EXCLUDED references (atomic counters):

```python
from plain.postgres.expressions import Excluded

PageView.query.upsert(
    path="/about",
    defaults={"count": 1},
    conflict_defaults={"count": F("count") + Excluded("count")},
    unique_fields=["path"],
)
```

#### get_or_create vs update_or_create vs upsert

These are **three different operations**:

|                                      | get_or_create                | update_or_create                             | upsert (proposed)                    |
| ------------------------------------ | ---------------------------- | -------------------------------------------- | ------------------------------------ |
| **Intent**                           | "Get existing or create new" | "Find and update, or create"                 | "Write this data — insert or update" |
| **Modifies existing?**               | Never                        | Always                                       | Always                               |
| **Queries**                          | 1-2                          | 2+                                           | **1**                                |
| **Race-safe?**                       | Retry on IntegrityError      | Lock (but nothing to lock before row exists) | **Atomic**                           |
| **Python logic between read/write?** | N/A                          | Yes                                          | No (single SQL)                      |

- **`upsert()`** — new. Replaces `update_or_create()` for the common case
- **`get_or_create()`** — keep. Genuinely different (never modifies existing rows)
- **`update_or_create()`** — deprecate. Use `upsert()` or explicit `for_update().get()` + manual logic

### 7. RETURNING on update() and delete()

```python
# Update + get rows back
jobs = Job.query.where(
    Job.status.eq("pending"),
).for_update(skip_locked=True)[:1].update(
    status="running", worker="w1",
).returning()

# Delete + archive
deleted = OldEvent.query.where(
    OldEvent.created_at.lt(cutoff),
).delete().returning("id", "payload")
```

### 8. Delete cascade

Currently `delete()` uses a Python-side cascade collector: loads all related objects into memory, follows every FK, deletes in reverse dependency order. This is a Django multi-DB pattern — it exists because not all databases handle CASCADE the same way.

Postgres handles all of this natively via FK constraint actions (`ON DELETE CASCADE`, `ON DELETE SET NULL`, `ON DELETE RESTRICT`). The Python collector is redundant if FK constraints are set up correctly — and Plain already sets them up.

```python
# Current: Python loads every related object, walks the graph, deletes one by one
# For a table with 100k rows and 5 FK relationships, this loads ~500k objects into memory

# Proposed: just DELETE and let Postgres handle cascading
User.query.where(User.is_active.eq(False)).delete()  # Postgres ON DELETE CASCADE handles related rows
```

This is a significant behavior change. The Python collector also handles `PROTECT` (raise before delete) and pre-delete hooks. Need to think about how to preserve those semantics while delegating the actual cascading to Postgres.

### 9. Efficient bulk_update

Currently `bulk_update()` generates a CASE/WHEN pattern:

```sql
UPDATE users SET
    name = CASE WHEN id = 1 THEN 'Alice' WHEN id = 2 THEN 'Bob' END,
    email = CASE WHEN id = 1 THEN 'a@x.com' WHEN id = 2 THEN 'b@x.com' END
WHERE id IN (1, 2)
```

This is slow for large batches. Postgres-native approach using UPDATE FROM VALUES:

```sql
UPDATE users SET name = data.name, email = data.email
FROM (VALUES (1, 'Alice', 'a@x.com'), (2, 'Bob', 'b@x.com')) AS data(id, name, email)
WHERE users.id = data.id
```

Much more efficient — single scan, no conditional branching per row. Could also support RETURNING for bulk update:

```python
updated = User.query.bulk_update(users, fields=["name", "email"]).returning()
```

### 10. Advisory locks

```python
from plain.postgres import advisory_lock

with advisory_lock("import-users"):
    do_work()

# Non-blocking
lock = advisory_lock("import-users")
if lock.try_acquire():
    try:
        do_work()
    finally:
        lock.release()
```

String keys hashed to int64. Replace Redis/ZooKeeper for single-instance cron jobs, rate limiting, distributed coordination.

### 11. Per-transaction isolation levels

```python
from plain.postgres import transaction

with transaction.atomic(isolation="serializable"):
    ...

with transaction.atomic(isolation="repeatable_read"):
    ...

with transaction.atomic(read_only=True):
    ...
```

### 12. TRUNCATE

```python
from plain.postgres import truncate

truncate(MyModel)
truncate(MyModel, cascade=True, restart_identity=True)
truncate(MyModel, OtherModel, cascade=True)
```

### 13. COPY for bulk loading

```python
rows = [(name, email, now) for name, email in data]
User.query.copy_from(rows, fields=["name", "email", "created_at"])
```

Orders of magnitude faster than INSERT for 100k+ rows. No RETURNING, no ON CONFLICT.

### 14. LISTEN/NOTIFY

```python
from plain.postgres import notify, listen

notify("jobs_available", payload='{"queue": "default"}')

async for notification in listen("jobs_available"):
    process(notification.payload)
```

Could underpin `plain-jobs` (notify on insert instead of polling) and future real-time features.

---

## Summary: what a query looks like end-to-end

```python
# Current (Django-inherited)
users = (
    User.query
    .filter(is_active=True, email__contains="@example.com")
    .exclude(role="admin")
    .select_related("profile")
    .prefetch_related("posts")
    .only("id", "email", "profile__bio")
    .order_by("-created_at")
    .distinct()[:10]
)

# Proposed (Postgres-native)
users = (
    User.query
    .where(
        User.is_active.eq(True),
        User.email.contains("@example.com"),
        ~User.role.eq("admin"),
    )
    .join("profile")
    .prefetch("posts")
    .select(User.id, User.email, User.profile.bio)
    .order_by(User.created_at.desc())
    .distinct()[:10]
)
```

---

## Implementation priority

| Priority | Feature                                | Effort | Impact                                          |
| -------- | -------------------------------------- | ------ | ----------------------------------------------- |
| 1        | `upsert()` / `bulk_upsert()`           | Medium | High — solves race conditions                   |
| 2        | RETURNING on `update()` / `delete()`   | Medium | High — atomic read-write patterns               |
| 3        | `where()` + typed field methods        | Large  | High — type safety, SQL clarity                 |
| 4        | `select()` consolidation               | Medium | Medium — simplifies 5 methods → 1               |
| 5        | `join()` / `prefetch()` rename         | Small  | Medium — clarity                                |
| 6        | `for_update()` + lock mode variants    | Small  | Medium — better concurrency                     |
| 7        | `sql()` with model-aware interpolation | Large  | Medium — replaces raw/extra/expression wrappers |
| 8        | Advisory locks                         | Small  | Medium — replaces Redis                         |
| 9        | Efficient bulk_update (VALUES)         | Medium | Medium — large batch performance                |
| 10       | Per-transaction isolation              | Small  | Medium — small change to atomic()               |
| 11       | Delete cascade → Postgres-native       | Medium | Medium — performance, but behavior change       |
| 12       | `truncate()`                           | Small  | Low — utility                                   |
| 13       | COPY bulk load                         | Medium | Situational — very large datasets               |
| 14       | LISTEN/NOTIFY                          | Large  | Future — needs async story                      |

## Open questions

### 1. `select()` return type

When you select a subset of columns, what Python type do you get back?

**A) Model instances with deferred fields**

```python
user = User.query.select(User.id, User.email).first()
# type: User (with bio, name, etc. deferred — accessing them triggers a query)
```

Pros: familiar, can pass the object to functions expecting a User. Cons: deferred field access is a hidden query trap, type is a lie (it's not a full User).

**B) Typed dicts**

```python
user = User.query.select(User.id, User.email).first()
# type: TypedDict with id: int, email: str
```

Pros: honest about what you have, no hidden queries. Cons: can't pass to functions expecting User, harder to type in practice (generated TypedDicts?).

**C) select() returns model instances by default, project() for dicts/custom types**

```python
user = User.query.select(User.id, User.email).first()      # User instance, deferred fields
row = User.query.project(User.id, User.email).first()       # dict or named tuple
row = User.query.project(User.id, User.email, as_type=UserRow).first()  # typed dataclass
```

Pros: clear intent split. Cons: two methods instead of one.

### 2. RETURNING API shape

**A) Method on result (call after)**

```python
jobs = Job.query.where(...).update(status="running").returning()
deleted = Event.query.where(...).delete().returning("id")
```

Pros: reads naturally left-to-right ("update, then give me the results"). Cons: the SQL must be planned before `.update()` executes, so `.returning()` would need to retroactively change the query — or `.update()` returns a lazy result that executes on `.returning()`.

**B) Queryset chain (set before)**

```python
jobs = Job.query.where(...).returning().update(status="running")
deleted = Event.query.where(...).returning("id").delete()
```

Pros: composes with queryset cloning, SQL is fully known before execution. Cons: reads a bit backwards ("returning... what? oh, the update").

**C) Parameter on the write method**

```python
jobs = Job.query.where(...).update(status="running", returning=True)
deleted = Event.query.where(...).delete(returning=["id"])
```

Pros: simple, no new methods. Cons: changes the return type based on a flag (int vs list), which is hard to type.

### 3. `sql()` parameter routing

How do parameters in `sql()` get type-processed (encrypted fields encrypt, dates format, etc.)?

**A) Match by name to fields in the query**

```python
User.query.sql("SELECT * FROM {User} WHERE {User.email} = {email}", email="foo")
# {email} matched to User.email because the name matches → routed through EmailField.get_db_prep_value
```

Pros: magic-free for common cases. Cons: ambiguous when param name doesn't match a field name, breaks for computed values.

**B) Explicit field annotation**

```python
User.query.sql("SELECT * FROM {User} WHERE {User.email} = {email:User.email}", email="foo")
# {email:User.email} explicitly says "process this through User.email's field"
```

Pros: unambiguous. Cons: verbose for common cases.

**C) No field processing — just parameterize**

```python
User.query.sql("SELECT * FROM {User} WHERE {User.email} = {email}", email="foo")
# {email} → $1 with value "foo", no field processing
```

Pros: simplest, predictable. Cons: encrypted fields don't auto-encrypt, dates aren't auto-formatted. But: psycopg3 handles most Python→Postgres type conversion natively, and encrypted fields are the exception not the rule.

### 4. `sql()` result typing

**A) Model instances when `{Model.*}`, dicts otherwise**

```python
users = User.query.sql("SELECT {User.*} FROM {User}")  # → list[User]
rows = User.query.sql("SELECT {User.id}, count(*) FROM {User} GROUP BY 1")  # → list[dict]
```

Pros: model instances for full-row queries (the common case). Cons: dicts are untyped.

**B) Always require explicit result type**

```python
users = User.query.sql("SELECT {User.*} FROM {User}", result_type=User)  # → list[User]
stats = User.query.sql("SELECT ...", result_type=UserStats)  # → list[UserStats]
```

Pros: always explicit, always typed. Cons: verbose for the common `{Model.*}` case.

**C) Infer model from `{Model.*}`, require `result_type` for custom projections**

```python
users = User.query.sql("SELECT {User.*} FROM {User}")  # → list[User] (inferred)
stats = User.query.sql("SELECT ...", result_type=UserStats)  # → list[UserStats] (explicit)
raw = User.query.sql("SELECT 1")  # → list[Row] (generic named tuple)
```

Pros: best of both — zero boilerplate for model queries, typed for custom projections. Cons: inference magic.

### 5. FK traversal boundary

`filter(profile__city="NYC")` auto-generates a JOIN. Where does the ORM stop?

**A) Single-hop FK traversal stays in ORM**

```python
User.query.where(User.profile.city.eq("NYC"))  # ORM generates LEFT JOIN
User.query.where(User.profile.company.name.eq("Acme"))  # Also ORM? Two hops.
```

Pros: covers the common case (most FK traversal is 1-2 hops). Cons: where's the line? Each hop adds a JOIN — at some point you should be explicit.

**B) All FK traversal → sql()**

```python
# No FK traversal in where() — only direct fields
User.query.where(User.profile_id.eq(42))  # Fine — direct field
# For FK traversal, use sql():
User.query.sql("""
    SELECT {User.*} FROM {User}
    JOIN {Profile} ON {Profile.id} = {User.profile_id}
    WHERE {Profile.city} = {city}
""", city="NYC")
```

Pros: clean boundary — ORM is single-table only. Cons: very common pattern pushed to SQL layer.

**C) FK traversal via explicit join()**

```python
User.query.join("profile").where(Profile.city.eq("NYC"))
```

Pros: explicit about the JOIN, still typed. Cons: needs to solve how `Profile.city` references the joined table in the where clause.

### 6. Delete cascade

**A) Drop Python collector, use Postgres CASCADE**

```python
User.query.where(...).delete()  # DELETE FROM users WHERE ...; Postgres handles CASCADE
```

Pros: fast, simple, Postgres-native. Cons: PROTECT checks must be in DB constraints (ON DELETE RESTRICT), no Python-side pre-delete logic.

**B) Keep Python collector as default, add fast path**

```python
User.query.where(...).delete()                # Python collector (current behavior)
User.query.where(...).delete(cascade="db")    # Postgres-native, fast
```

Pros: backwards compatible, opt-in fast path. Cons: two code paths to maintain.

**C) Drop Python collector, add PROTECT as a preflight/constraint check**

```python
# PROTECT → ON DELETE RESTRICT in the FK constraint (enforced by Postgres)
# Pre-delete logic → use Postgres triggers or application-level checks before calling delete()
User.query.where(...).delete()  # Always Postgres-native
```

Pros: clean, fast. Cons: migration effort, triggers are a different paradigm.

### 7. Migration path

**A) Clean break**
Remove `filter()`, `select_related()`, etc. in a single release. The `/plain-upgrade` agent handles user code migration.

**B) Aliases during transition**
Keep `filter()` as an alias for `where()`, etc. for N releases. Emit deprecation warnings.

**C) Parallel APIs**
Both old and new APIs work indefinitely. Don't remove, just document the new way.

### 8. F() expressions in the ORM

`qs.update(count=F("count") + 1)` is single-table and very common. Does it stay?

**A) Keep, but change syntax to field references**

```python
User.query.where(...).update(count=User.count + 1)
# User.count + 1 returns an Expression, same as F("count") + 1 but typed
```

Pros: type-safe, common pattern stays in ORM. Cons: `User.count` as a class-level descriptor returning an Expression is new machinery.

**B) Keep F() as-is**

```python
User.query.where(...).update(count=F("count") + 1)
```

Pros: works today. Cons: stringly-typed, the thing we're trying to move away from.

**C) Push to sql()**

```python
User.query.sql("UPDATE {User} SET count = count + 1 WHERE {User.id} = {id}", id=user_id)
```

Pros: clean boundary. Cons: very common pattern becomes verbose.

### 9. Aggregate boundary

**A) Keep simple aggregates as methods, GROUP BY → sql()**

```python
User.query.count()                                    # ORM — stays
User.query.where(...).sum(User.balance)               # ORM — single-table aggregate
User.query.where(...).avg(User.age)                   # ORM — single-table aggregate

# GROUP BY → sql()
User.query.sql("""
    SELECT {User.role}, count(*), avg(age)
    FROM {User} GROUP BY {User.role}
""", result_type=RoleStats)
```

Pros: common aggregates stay typed, complex ones use SQL. Cons: need to add `sum()`, `avg()`, `max()`, `min()` to QuerySet.

**B) Only count() and exists(), everything else → sql()**

```python
User.query.count()   # stays
User.query.exists()  # stays
# sum, avg, max, min → sql()
```

Pros: minimal ORM surface. Cons: `User.query.where(is_active=True).sum(User.balance)` is very common.

**C) Keep aggregate() but with typed field references**

```python
result = User.query.aggregate(
    total=Sum(User.balance),
    avg_age=Avg(User.age),
)
# type: {"total": Decimal, "avg_age": float}
```

Pros: familiar, type-safe. Cons: another method to maintain, GROUP BY still needs sql().

### 10. Excluded expression syntax

**A) `Excluded("field")` — string-based, like F()**

```python
PageView.query.upsert(
    conflict_defaults={"count": F("count") + Excluded("count")},
    ...
)
```

Pros: consistent with F(). Cons: stringly-typed (the thing we're moving away from).

**B) `Excluded(Model.field)` — field reference**

```python
PageView.query.upsert(
    conflict_defaults={"count": PageView.count + Excluded(PageView.count)},
    ...
)
```

Pros: typed, consistent with the new field-reference pattern. Cons: slightly more verbose.

**C) Upsert handles it implicitly, complex cases → sql()**

```python
# Simple case: defaults are automatically EXCLUDED.field
PageView.query.upsert(path="/about", defaults={"count": 1}, unique_fields=["path"])
# → ON CONFLICT DO UPDATE SET count = EXCLUDED.count

# Atomic increment needs explicit expression:
PageView.query.upsert(
    path="/about",
    defaults={"count": 1},
    conflict_defaults={"count": PageView.count + 1},  # increment existing, no EXCLUDED needed
    unique_fields=["path"],
)

# Complex EXCLUDED logic → sql()
```

Pros: covers 80% without an Excluded class at all. Cons: can't reference the proposed value in the conflict expression without EXCLUDED.
