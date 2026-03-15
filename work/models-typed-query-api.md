---
labels:
  - plain-models
related:
  - models-encrypted-field
  - models-explicit-create-update
---

# plain-models: Typed Query API

Replace the stringly-typed `filter(**kwargs)` / `exclude(**kwargs)` query API with field-reference expressions that are type-checkable with standard Python typing. Establish a clear two-layer design: typed Python for common queries, raw SQL with model-aware interpolation for everything else.

## Problem

The current query API inherits Django's `**kwargs` pattern:

```python
User.query.filter(email="foo@bar.com")
User.query.filter(email__startswith="foo")
User.query.update(secret=F("name"))
User.query.order_by("-created_at")
```

This is fundamentally un-type-checkable without a mypy/pyright plugin:

- `filter(emial="foo")` — typo, no error
- `filter(email=5)` — wrong type, no error
- `update(secret=F("name"))` — bypasses encryption on an encrypted field, no error
- `order_by("emial")` — typo, no error

Beyond type checking, the current API also struggles with **field-level constraints**. Encrypted fields can't support lookups, indexes, or expression writes — but enforcing this requires scattered runtime hooks across the ORM (preflight checks, `get_lookup` overrides, `get_db_prep_save` guards). Each constraint requires knowing a different internal to override, and some hooks don't even exist.

Meanwhile, the Django-inherited expression system (`annotate()`, `Subquery()`, `OuterRef()`, `F()`, `Value()`, `Case()`, `When()`) is the worst of both worlds: not type-safe AND harder to read than the SQL it's hiding.

## Design

### Two layers

```
┌─────────────────────────────────────┐
│  Typed Python API                   │  90% of queries
│  where(), set(), order_by()         │  Type-checkable, field-constrained
├─────────────────────────────────────┤
│  Model-aware SQL                    │  10% of queries
│  sql() with {Model.field} refs      │  Full SQL power, field-aware binding
└─────────────────────────────────────┘
```

No middle layer. No `annotate()`, no `Subquery()`, no `OuterRef()`. Once you need joins, aggregation, window functions, or anything relational — write SQL.

### Layer 1: Typed Python API

Fields are already descriptors on the model class. At class level, `User.email` returns the Field object. The proposal is to give these field objects typed methods that return query expressions:

```python
# Filtering
User.query.where(
    User.email.eq("foo@bar.com"),
    User.age.gte(18),
)

# Equivalent to current: filter(email="foo@bar.com", age__gte=18)

# OR conditions
User.query.where(
    User.email.eq("foo@bar.com") | User.email.eq("bar@baz.com"),
)

# Negation
User.query.where(
    ~User.is_active.eq(True),
)

# Ordering
User.query.order_by(
    User.created_at.desc(),
)

# Update
User.query.where(
    User.is_active.eq(True),
).update(
    User.email.set("redacted@example.com"),
)
```

#### Why methods, not operators

`User.email == "foo"` (operator overloading) is the SQLAlchemy approach. Methods are better for Plain:

- `__eq__` returning something other than `bool` breaks Python semantics — `assert User.email == "foo"` silently passes (truthy expression object), confusing debugging and tools
- `.eq()`, `.gte()`, `.contains()` are explicit and greppable
- Methods can have precise type signatures — `.eq(value: T)` where `T` is the field's type parameter
- Absence of a method is a clear signal — encrypted fields don't have `.eq()`, period

#### Field method surface

```python
class Field(Generic[T]):
    # Comparison
    def eq(self, value: T) -> Condition: ...
    def neq(self, value: T) -> Condition: ...
    def gt(self, value: T) -> Condition: ...
    def gte(self, value: T) -> Condition: ...
    def lt(self, value: T) -> Condition: ...
    def lte(self, value: T) -> Condition: ...
    def is_in(self, values: Iterable[T]) -> Condition: ...
    def is_null(self) -> Condition: ...

    # Update
    def set(self, value: T | Expression) -> Assignment: ...

    # Ordering
    def asc(self) -> Ordering: ...
    def desc(self) -> Ordering: ...
```

Specific field types add their own methods:

```python
class TextField(Field[str]):
    def contains(self, value: str) -> Condition: ...
    def startswith(self, value: str) -> Condition: ...
    def endswith(self, value: str) -> Condition: ...

class IntegerField(Field[int]):
    # Arithmetic for expressions
    def __add__(self, other: int) -> Expression[int]: ...
    def __sub__(self, other: int) -> Expression[int]: ...
```

#### Encrypted field constraints via type surface

An encrypted field simply has a smaller method surface:

```python
class EncryptedTextField(Field[str]):
    # No eq, no contains, no startswith — they don't exist
    # No asc, no desc — can't order by encrypted values

    def is_null(self) -> Condition: ...          # Only lookup that works
    def set(self, value: str) -> Assignment: ... # str only, no Expression
```

Then:

```python
# Type error — EncryptedTextField has no .eq()
User.query.where(User.secret.eq("foo"))

# Type error — .set() accepts str, not Expression
User.query.update(User.secret.set(F("name")))

# Works
User.query.where(User.secret.is_null())

# Works
User.query.update(User.secret.set("new-secret"))
```

No preflight checks needed. No runtime hooks in query internals. No `supports_indexing` flags. The field doesn't have the methods. The type checker enforces it statically, and anyone without a type checker gets `AttributeError` at runtime.

Index/constraint validation works the same way — `model_options` can require fields to satisfy a protocol:

```python
class Indexable(Protocol):
    def asc(self) -> Ordering: ...
    def desc(self) -> Ordering: ...

# Encrypted fields don't satisfy Indexable — type error in index definition
```

### Layer 2: Model-aware SQL

For anything beyond simple filters — joins, aggregation, window functions, CTEs, subqueries — write SQL with model-aware interpolation:

```python
results = User.query.sql("""
    SELECT {User.*}
    FROM {User}
    WHERE {User.email} = {email}
    AND {User.created_at} > {cutoff}
""", email="foo@bar.com", cutoff=last_week)
```

How interpolation works:

- `{User}` — resolves to the table name
- `{User.*}` — expands to the column list, with field processing (decryption wrappers for encrypted fields, etc.)
- `{User.email}` — resolves to the column name
- `{email}` — parameterized value, goes through the corresponding field's `get_db_prep_value` (so encrypted fields encrypt, date fields format, etc.)

The parameter-to-field mapping could work by matching parameter names to field names in the query context, or by explicit annotation.

A more complex example:

```python
results = User.query.sql("""
    SELECT {User.id}, {User.email}, count({Order.id}) AS order_count
    FROM {User}
    LEFT JOIN {Order} ON {Order.user_id} = {User.id}
    WHERE {User.created_at} > {cutoff}
    GROUP BY {User.id}
    HAVING count({Order.id}) > {min_orders}
""", cutoff=last_week, min_orders=5)
```

Results are bound to model instances when possible (the `{User.*}` case), or returned as named tuples / typed dicts for custom projections.

### What this replaces

| Current (Django-inherited)              | New                                   |
| --------------------------------------- | ------------------------------------- |
| `filter(email="foo")`                   | `where(User.email.eq("foo"))`         |
| `filter(email__startswith="foo")`       | `where(User.email.startswith("foo"))` |
| `exclude(is_active=True)`               | `where(~User.is_active.eq(True))`     |
| `order_by("-created_at")`               | `order_by(User.created_at.desc())`    |
| `update(email="new")`                   | `update(User.email.set("new"))`       |
| `annotate(...).filter(...).values(...)` | `sql("""...""")`                      |
| `Subquery(OuterRef(...))`               | `sql("""...""")`                      |
| `F("field") + Value(1)`                 | `sql("""...""")` or `User.field + 1`  |

### `where()` vs `filter()`

Use `where()` as the method name. It maps directly to SQL `WHERE`, is unambiguous, and clearly replaces both `filter()` and `exclude()`.

Multiple arguments to `where()` are AND-ed (same as `filter()`):

```python
User.query.where(
    User.email.contains("@example.com"),
    User.is_active.eq(True),
)
```

## Industry context

- **SQLAlchemy 2.0**: Went through exactly this transition (stringly-typed → expression-based). Took years. Uses operator overloading (`Column.__eq__` returns `BinaryExpression`). Fully type-checkable with `Mapped[T]`.
- **Peewee**: Field expressions with operator overloading (`User.email == "foo"`). Simple and type-friendly.
- **JOOQ (Java)**: SQL-shaped builder that mirrors SQL clause order. Proven at scale. Fully type-safe.
- **Prisma**: Generated typed client from schema. Different approach (codegen) but same goal.
- **Kysely (TypeScript)**: SQL builder with full type inference. No ORM abstraction — just typed SQL.
- **EdgeDB/EdgeQL**: Custom query language with type safety. Too far from SQL for Plain's goals.

The trend across ecosystems is clear: stringly-typed ORMs are being replaced by type-safe alternatives. Python's type checking ecosystem (pyright, mypy) is mature enough to support this now.

## Future: PEP 827 (Type Manipulation)

[PEP 827](https://peps.python.org/pep-0827/) (draft, targeting Python 3.15) proposes TypeScript-style type manipulation — conditional types, mapped types, type-level introspection via `Members`/`Attrs`, and construction via `NewProtocol`/`NewTypedDict`. If accepted, it could enable:

- **Return type narrowing for `.sql()`** — deriving result types from `{User.*}` or `{User.email}` references
- **Model type derivation** — `Create[User]` that omits PK and applies defaults, without hand-written types
- **Field constraint protocols** — `Indexable`, `Filterable` etc. checked at the type level via `IsAssignable`

None of this changes the near-term design (the typed Python API works with today's typing), but it's worth watching for the SQL layer and model derivation use cases.

## Open questions

- **Migration path**: Can `filter()` and `where()` coexist during transition? Or is it a clean break?
- **Related field traversal**: `filter(profile__city="NYC")` traverses a FK. What does `where(User.profile.city.eq("NYC"))` look like? Does the field descriptor chain, or does this fall to the SQL layer?
- **Aggregation in the typed layer**: Should `count()`, `sum()`, `avg()` exist as typed Python, or are they always SQL layer? Simple `User.query.count()` should stay, but `GROUP BY` with aggregates is probably SQL territory.
- **`.sql()` return types**: How to type the results of arbitrary SQL? Model instances for `{User.*}`, but what about custom projections? `TypedDict`? `NamedTuple`? Dataclasses?
- **`.sql()` interpolation**: How does parameter-to-field mapping work for `get_db_prep_value`? By matching param names to column names in the query? Explicit `{email:User.email}` syntax?
- **Condition composability**: How do `|` (OR) and `~` (NOT) work on `Condition` objects? Operator overloading on `Condition` is fine (unlike on fields) since `Condition` is a query-internal type, not a Python value.

## Nearer-term alternative: field capability flags

Without redesigning the query API, field constraints could be enforced via declarative flags checked by the ORM at specific points:

```python
class EncryptedFieldMixin:
    supports_indexing = False
    supports_expressions = False

# ORM checks these in model setup, add_update_values, etc.
```

This doesn't solve type checking but does centralize the constraint enforcement that's currently scattered across preflight checks, `get_lookup` overrides, and missing hooks. It could be implemented now and would remain compatible with the typed query API if/when that lands (the flags would become redundant as the method surface takes over).

Another incremental step: a `check_model_setup()` hook called after model class construction, giving fields a chance to validate their configuration (e.g., encrypted field in a constraint) as a hard `ImproperlyConfigured` error rather than a skippable preflight check.
