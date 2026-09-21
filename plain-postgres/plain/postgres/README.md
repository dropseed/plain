# plain.postgres

**Model your data and store it in a database.**

- [Overview](#overview)
- [Database connection](#database-connection)
    - [Middleware](#middleware)
    - [Bypassing a connection pooler for management operations](#bypassing-a-connection-pooler-for-management-operations)
- [Querying](#querying)
- [Returning affected rows](#returning-affected-rows)
- [Schema management](#schema-management)
    - [Syncing](#syncing)
    - [Structural migrations](#structural-migrations)
    - [Data migrations](#data-migrations)
    - [Convergence](#convergence)
- [Fields](#fields)
- [Relationships](#relationships)
- [Constraints](#constraints)
- [Forms](#forms)
- [Architecture](#architecture)
- [Diagnostics](#diagnostics)
- [Tracing](#tracing)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

```python
# app/users/models.py
from datetime import datetime

from plain import postgres
from plain.postgres import Field, types
from plain.passwords.models import PasswordField


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = PasswordField()
    is_admin: Field[bool] = types.BooleanField(default=False)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    def __str__(self) -> str:
        return self.email
```

Annotate each field with `Field[T]` (the value type) — that's what gives the
model a type-checked constructor: `User(email="a@b.com")` flags wrong value
types, unknown field names, and missing required fields.

Annotating is not per-model opt-in. `postgres.Model` carries the transform, so
the checker synthesizes every subclass's constructor from its annotated
attributes and nothing else. Drop the annotation from `email` above and it stops
being a constructor argument at all — `User(email="a@b.com")` is then rejected as
an unknown argument. The runtime doesn't care either way, but if you run a type
checker, every model has to be annotated.

A field is optional in that constructor only when its definition passes
`default=` (this is general, not nullable-specific — a `required=False` field
with no `default=` is still a required constructor arg), so nullable fields use
`Field[T | None]` with `default=None`. The runtime already treats a nullable
field as optional — constructing without it yields `None` — so `default=None`
exists for the checker; it persists nothing and changes no schema.
`plain preflight` lists the nullable fields still missing one
(`postgres.nullable_field_without_default`). DB-owned fields (`id`,
`create_now`, generated values) are auto-excluded from the constructor.

Field types declared outside `plain.postgres.types` — `PasswordField`, or one of
your own — are the exception: their stub still types the value, but they are
always _optional_ in the constructor, even when the column is `NOT NULL`. PEP
681 recognizes a field declaration by matching the constructor against a fixed
list, and that list is baked into `plain.postgres` where a third-party field
type can't join it, so the checker reads the assignment as a plain default
value. Wrong value types and unknown field names are still caught; only
requiredness is lost, and omitting one surfaces as a `NOT NULL` error on insert
instead. [Sharing fields across models](#sharing-fields-across-models) shows how
a package that ships a field type can keep it required.

Every model automatically includes an `id` field which serves as the primary
key. The name `id` is reserved and can't be used for other fields.

You can create, update, and delete instances of your models:

```python
from .models import User


# Create a new user
user = User.query.create(
    email="test@example.com",
    password="password",
)

# Update a user
user.email = "new@example.com"
user.update()

# Delete a user
user.delete()

# Query for users
admin_users = User.query.filter(is_admin=True)
```

## Database connection

Configure the database with a single URL. The canonical Plain setting is `POSTGRES_URL`:

```python
# app/settings.py
POSTGRES_URL = "postgresql://user:password@localhost:5432/dbname"
```

Or via environment variable:

```sh
PLAIN_POSTGRES_URL=postgresql://user:password@localhost:5432/dbname
```

Plain also reads the `DATABASE_URL` environment variable as a fallback — it's the widely-used convention for Postgres connection strings, so most hosting setups work without extra configuration:

```sh
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

Precedence (highest to lowest): `PLAIN_POSTGRES_URL` → `POSTGRES_URL` in `settings.py` → `DATABASE_URL` environment variable.

The URL supports any libpq connection parameter as a query string — for example `?sslmode=require&application_name=web&connect_timeout=10`. These are parsed and passed through to the driver.

To explicitly disable the database (e.g. during Docker builds where no database is available), set the URL to the string `none`:

```sh
PLAIN_POSTGRES_URL=none
```

### Middleware

Connections are checked out lazily on first use and returned to the pool when the HTTP request finishes. That's handled by [`DatabaseConnectionMiddleware`](./middleware.py#DatabaseConnectionMiddleware) — add it to `MIDDLEWARE` once you install `plain.postgres`:

```python
# app/settings.py
MIDDLEWARE = [
    "plain.postgres.DatabaseConnectionMiddleware",
    # ...other middleware
]
```

Place it near the top so downstream middleware can use the database inside `before_request` / `after_response` and still have the connection returned cleanly at the end.

For `StreamingResponse` / `AsyncStreamingResponse`, the connection is returned after the body is fully drained (not when the view returns), so generators that lazily query the database — for example `Model.query.iterator()` or raw cursor loops — keep their cursor alive until the last chunk is sent.

Without the middleware, connections keep living on their thread until something explicitly calls `plain.postgres.db.return_database_connection()` (or the process exits). That's fine for short-lived scripts but wastes a connection per thread in long-running servers.

### Bypassing a connection pooler for management operations

Transaction-mode poolers (PlanetScale, Supabase's pooler, Neon's pooler, standalone pgbouncer in transaction mode) can't run DDL, long transactions, or `pg_dump`. To work around this, set a second URL that management commands use to reach Postgres directly:

```sh
PLAIN_POSTGRES_URL=postgresql://app@pooler:6432/myapp
PLAIN_POSTGRES_MANAGEMENT_URL=postgresql://app@postgres:5432/myapp
```

When `POSTGRES_MANAGEMENT_URL` is set, these commands connect through it instead of `POSTGRES_URL`:

- `plain migrations create`, `plain migrations apply`, `plain migrations list`, `plain migrations prune`
- `plain postgres sync`, `plain postgres converge`, `plain postgres schema`
- `plain postgres diagnose`, `plain postgres drop-unknown-tables`, `plain postgres shell`

When it's unset, all commands use `POSTGRES_URL` — there's no behavior change for existing apps.

To route custom code through the management connection, use the `use_management_connection()` context manager:

```python
from plain.postgres import use_management_connection

with use_management_connection():
    # Any get_connection() / ORM calls inside this block use POSTGRES_MANAGEMENT_URL.
    run_custom_schema_change()
```

You _can_ point the two URLs at different Postgres roles — e.g. a least-privilege DML role for runtime and a DDL-capable role for management. Plain does not currently automate the grant/ownership plumbing that split requires (default privileges for newly-created tables, ownership reassignment, preflight checks that the runtime role can see the schema). If you adopt that pattern, you're responsible for wiring those up yourself.

## Querying

Models come with a powerful query API through their [`QuerySet`](./query.py#QuerySet) interface:

```python
# Get all users
all_users = User.query.all()

# Filter users
admin_users = User.query.filter(is_admin=True)
recent_users = User.query.filter(created_at__gte=datetime.now() - timedelta(days=7))

# Get a single user
user = User.query.get(email="test@example.com")

# Complex queries with Q objects
from plain.postgres import Q

users = User.query.filter(Q(is_admin=True) | Q(email__endswith="@example.com"))

# Ordering
users = User.query.order_by("-created_at")

# Limiting results
first_10_users = User.query.all()[:10]
```

For more advanced querying options, see the [`QuerySet`](./query.py#QuerySet) class.

### Typed conditions with where()

`where()` is a typed alternative to `filter()`. Instead of string keyword lookups, you build each condition from a field, so a type checker catches a misspelled field or a wrong value type at the call site:

```python
from datetime import datetime

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    role: Field[str] = types.TextField(max_length=20)
    age: Field[int | None] = types.IntegerField(allow_null=True, default=None)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(update_now=True)


# Each argument is a condition; multiple arguments are ANDed together.
admins = User.query.where(
    User.role.equals("admin"),
    User.age.gte(18),
)
```

Every field exposes `equals`, `not_equal`, `gt`, `gte`, `lt`, `lte`, `is_null`, and `is_in`. Text fields add `contains`, `startswith`, and `endswith`, plus their case-insensitive forms `icontains`, `istartswith`, `iendswith`, and `iequals` (the typed spelling of `filter(field__iexact=...)`). Each returns a `Q`, so you can combine them with `|` and `&` or negate with `~`:

```python
# Membership, negation, and OR
User.query.where(User.role.is_in(["admin", "staff"]))
User.query.where(~User.role.equals("guest"))
User.query.where(User.email.endswith("@example.com") | User.role.equals("admin"))
```

`is_in` binds the whole collection as one array parameter -- `WHERE "role" = ANY(%s::text[])` rather than `IN (%s, %s)` -- so one statement text covers any number of values. Two things follow: `pg_stat_statements` groups every call into a single entry instead of one per list length, and an empty list is no longer a special case (it matches nothing by running a real query, where before it ran none at all). Pass a queryset instead of a collection and it stays a subquery: `WHERE "id" IN (SELECT ...)`.

A `None` in the collection raises `ValueError`. NULL is not a value a comparison can match -- it would match nothing, and negated it would exclude every row -- so it belongs in `is_null()`. Combine them when you want both:

```python
User.query.where(User.role.is_in(["admin"]) | User.role.is_null())
```

`~` negates whatever it wraps, which is what you want for a composite condition but not for a null check. `is_null()` takes a flag, and the two compile differently:

```python
User.query.where(~User.age.is_null())  # WHERE NOT ("age" IS NULL)
User.query.where(User.age.is_null(False))  # WHERE "age" IS NOT NULL
```

Both match the same rows. `is_null(False)` is the conversion for `filter(age__isnull=False)` and emits the SQL you would write by hand, so reach for it and keep `~` for negating a condition that isn't a null check.

A comparison can also take another column of the same value type, instead of a value:

```python
# Q(updated_at__gt=F("created_at"))
User.query.where(User.updated_at.gt(User.created_at))
```

`equals`, `not_equal`, `gt`, `gte`, `lt`, and `lte` all accept one. The column has to belong to the same model, which `where()` checks on both sides, and it has to be the same value type — comparing an `int` column against a `str` one is a type error.

A **nullable column is a different value type** to the checker — `Field[int | None]` is not a `Field[int]` — so the two directions aren't the same. A non-null column accepts a nullable one on the right; a nullable one on the left won't accept a non-null column, because there's no way to name its value type without the `None`. Compare the other way round, or drop to `filter(age__lt=F("other"))`.

An `F()` expression works too, but that arm is untyped: an expression's output type isn't tracked, so nothing checks it against the column. `F()` is the same escape hatch here that it is in `filter()`.

**A condition _is_ a `Q`**, so these replace `Q` everywhere, not just in `filter()`. Anything that takes a `Q` takes one unchanged — `When()`, including the ones inside a `Case()`, and an aggregate's `filter=`:

```python
from plain.postgres.aggregates import Count
from plain.postgres.expressions import Case, Value, When

User.query.annotate(
    tier=Case(When(User.age.gte(18), then=Value("adult")), default=Value("minor"))
)
User.query.values("role").annotate(adults=Count("id", filter=User.age.gte(18)))
```

```sql
-- the Case annotation
CASE WHEN "age" >= %s THEN %s ELSE %s END AS "tier"
-- the Count annotation
COUNT("id") FILTER (WHERE "age" >= %s) AS "adults"
```

Conditions traverse foreign keys — accessing a field through a relation builds the joined lookup:

```python
# Q(author__email="a@example.com")
Post.query.where(Post.author.email.equals("a@example.com"))
```

A relation is a path to traverse, not a field, so it carries no conditions of its own. To match on the relation itself, traverse to the key it points at — that's the typed spelling of `filter(author=author)`, and it compiles to the same SQL:

```python
Post.query.where(Post.author.id.equals(author.id))
Post.query.where(Post.author.id.is_in([a.id for a in authors]))
Post.query.where(Post.author.id.is_null())  # nullable relation
```

(`is_in` is the one that reads differently: it binds an array, as above, where `filter(author__in=[...])` writes out a placeholder per value. Same rows, same column.)

`Post.author.equals(author)` raises `AttributeError` naming this spelling (an `AttributeError`, so `hasattr` and `getattr(..., default)` keep behaving). It isn't an oversight: to the type checker `Post.author` is `type[Author]`, which is what makes `Post.author.email.equals(...)` type-check, and a condition method there would be a runtime method the checker rejects.

Traversal starts from a **forward foreign key**. Once inside one, every relation you pass through is another hop, many-to-many included — `WidgetTag.widget.tags.name.equals("metal")` builds `Q(widget__tags__name="metal")` — and the same rule applies to the relation itself: `WidgetTag.widget.tags.equals(tag)` points you at `WidgetTag.widget.tags.id.equals(tag.id)`.

A class-level many-to-many (`Widget.tags`) is _not_ an entry point: it has no traversal wiring, and it is typed `ManyToManyManager[Tag]`, so it could not be typed as one either. Use the string path there — `Widget.query.filter(tags__name="metal")`. Reverse relations aren't traversable for the same reason (a reverse accessor is a `ClassVar`, so there is nothing for the related model to offer the checker), and the error says so.

A traversed field _is_ the related field, carrying the relation path as its name — so it offers exactly the conditions that field offers, including an encrypted field's refusals.

`field.lookup_path` is that path — `"email"` for a column on the model, `"user__email"` for a traversed one — so generic code handed a field reference can build a string lookup (`Q(**{f"{field.lookup_path}__icontains": term})`), an `order_by()` term, or a `values()` key without assembling the path itself.

**`where()` preserves the order you wrote; `filter()` sorted its kwargs alphabetically.** Converting a multi-condition `filter()` can change the WHERE clause text and the parameter order, though not which rows it matches:

```sql
-- filter(role="admin", email="a@example.com")
WHERE ("email" = %s AND "role" = %s)  -- params: ('a@example.com', 'admin')
-- where(User.role.equals("admin"), User.email.equals("a@example.com"))
WHERE ("role" = %s AND "email" = %s)  -- params: ('admin', 'a@example.com')
```

Kwargs you already wrote alphabetically convert unchanged. Where the source order wasn't alphabetical, preserving it changes the predicate structure — a test asserting on generated SQL notices, and so can `pg_stat_statements`, which groups by structure rather than literal text and files the reordered statement as a new entry.

**Conditions are strict where `filter()` was lenient — to the type checker.** `equals` takes the field's value type, so `User.age.equals("18")` and a `Field[UUID]`'s `.equals("3f2504e0-4f89-11d3-9a0c-0305e82c3301")` are type errors where `filter(age="18")` and `filter(uuid="3f2504e0-4f89-11d3-9a0c-0305e82c3301")` were not. Runtime coercion is unchanged: `User.age.equals("18")` still coerces the string and runs, exactly as the kwarg did.

So the strictness lands on the caller. Code holding a string from a CLI argument, URL segment, or session parses it first — `int(raw)`, `uuid.UUID(raw)` — and an invalid value raises `ValueError` there, before the ORM is involved, next to the input that was wrong.

**A condition belongs to the model whose field built it.** `Order.query.where(User.email.equals("x"))` raises `TypeError` naming both models. A type checker can't catch this — `Field[str]` is `Field[str]` whichever model declared it — and without the check the lookup name `"email"` just resolves against `Order`, which is silently the wrong column when both models have one. A traversed condition belongs to the model the traversal _started_ from, so `Order.query.where(Order.user.email.equals("x"))` is `Order`'s, not `User`'s. A hand-written `Q(email="x")` names no model and isn't checked — it's `filter()`'s untyped spelling and behaves like it.

**The terminals take conditions too, and `get()` takes a key.** Looking a row up by its primary key is the most common query there is, and spelling it `where(Model.id.equals(5)).get()` is a long way round, so `get()` has three entry points:

```python
User.query.get(5)  # by key
User.query.get(User.email.equals(x))  # by condition
User.query.where(...).get()  # exactly one row of a built query
```

The contract never moves: exactly one row, or `DoesNotExist`/`MultipleObjectsReturned`. `get_or_none()` takes the same three entry points and returns `None` instead of raising when nothing matches. `first()` and `last()` take conditions but no key, since `first(5)` would read as "the first 5".

Each one is sugar for `where(...)` plus the terminal, so the SQL is identical — `get(5)`, `where(User.id.equals(5)).get()` and `get(id=5)` all compile to the same statement. Multiple conditions AND together in the order written, exactly as `where()` does.

The key is the key's own type, so a value from a URL segment, session, or CLI argument is parsed first:

```python
User.query.get(int(raw_id))  # get("5") is a type error, and raises at runtime
```

Mixing a key with conditions is refused, and so is the key form on a `select()` queryset — a row has no key of its own, and `rows[5]` already means the sixth row.

[Encrypted fields](#encrypted-fields) reject value comparisons because their ciphertext is non-deterministic — only `is_null()` is available, and any other condition method (`equals`, `is_in`, …) raises `TypeError`. That holds on either side of a comparison: an encrypted column can't be the column another column is compared _against_ either, since that would match plaintext against ciphertext.

### Selecting columns with select()

`select()` pulls back specific columns as typed rows instead of model instances. You pass typed field references, and a type checker knows the exact shape of each row:

```python
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    age: Field[int | None] = types.IntegerField(allow_null=True, default=None)


# list-like of tuple[str, int | None], precisely typed
rows = User.query.where(User.age.gte(18)).select(User.email, User.age)
for email, age in rows:
    ...
```

There are three modes:

- **Tuples** (default) — one tuple per row, typed per column: `select(User.email, User.age)` yields `tuple[str, int | None]`.
- **Flat scalars** — a single column unwrapped, with `flat=True`: `select(User.email, flat=True)` yields `str`. `flat=True` accepts exactly one column.
- **Dataclasses** — map each column onto a dataclass with `result_type=`: `select(User.email, User.age, result_type=UserStats)` yields `UserStats`. Columns map to dataclass fields **positionally**, so the selection order must match the dataclass field order, and each selected field's name must match the dataclass field at the same position.

```python
from dataclasses import dataclass


@dataclass
class UserStats:
    email: str
    age: int | None


stats = User.query.select(User.email, User.age, result_type=UserStats)
```

The return value is a [`RowQuerySet`](./query.py#RowQuerySet) — that is the name to reach for when you need to annotate one:

```python
from plain.postgres import RowQuerySet


def adults() -> RowQuerySet[tuple[str, int | None]]:
    return User.query.where(User.age.gte(18)).select(User.email, User.age)
```

You can select expression columns too — `select(User.id, Sum("amount"))`, or an `F()` — but an expression column types as `Any` (its output type isn't tracked yet). The fields around it stay precise, so `select(User.id, Sum("amount"))` types as `tuple[int, Any]`.

Per-column typing runs to **ten columns**. An eleventh is still selected and still returns rows, but the row type degrades to `tuple[Any, ...]` — reach for `result_type=` when a row is that wide.

`select()` goes last in a chain: `annotate()` must come before it, because an annotation appends a column and would change the row shape out from under the type `select()` declared. `annotate()` after `select()` raises `TypeError` saying so. `prefetch()` is refused in both orders — a prefetch attaches related objects to a model instance's attributes, and a row has nowhere to put them; select the columns you need from the related model instead.

Re-selecting replaces the **column list**, not the joins: an expression that reached through a relation (`select(Upper("tags__name"))`) leaves its join in place, so a later `select(Widget.name)` still returns one row per joined row — and `count()`/`exists()` count those. This is `annotate(...)` followed by `values_list(...)` behaving as it always has; trimming joins no queryset needs any more is out of scope here.

`distinct()` with an `order_by()` on a column you didn't select returns duplicates: the ordering column has to go into the `SELECT` list for Postgres to sort by it, so `SELECT DISTINCT` deduplicates on that column too. Order by something you selected, or drop the ordering. This is `values_list()`'s behavior as well, not new to `select()`.

Columns annotated `Field[Any]` are rejected by `select()`, because `Any` satisfies the model-valued `__get__` overload and class access resolves as `type[Any]` rather than a field. That's the same reason the field-annotation guidance says never to annotate a field `Field[Any]` — use the concrete type, or `Field[object]` when the column really does hold arbitrary JSON, which `select()` types as `object`.

**`select()` returns rows, not partial model instances.** This is deliberate: a model instance with only some columns loaded is a type-level lie — the type checker thinks every field is present, so touching an unselected column looks fine but fails or fires a hidden query at runtime. Honest tuples/dataclasses keep the types truthful. As a result, iteration, `first()`, `get()`, `iterator()`, and slicing all return rows (`get()` still takes conditions; only its primary key form is refused), and anything that would read or write model rows, or change the selected columns — `update()`, `delete()`, `get_or_create()`, `values()`, `values_list()`, `annotate()`, `prefetch()` — raises `TypeError`. `update()` and `delete()` refuse a queryset in row mode however it got there, `values()` and `values_list()` included.

`select()` takes typed references only — a bare string like `select("email")` raises `TypeError` (use `User.email`).

**A column belongs to the model whose field built it**, the same as [a condition does](#querying-with-typed-conditions): `Order.query.select(User.email)` raises `TypeError` naming both models. A type checker can't catch it — `Field[str]` is `Field[str]` whichever model declared it — and without the check the name `"email"` just resolves against `Order`, silently the wrong column when both models have one. Expressions are unaffected: `F("email")` and `Upper("email")` take a string resolved against whatever query they land in, like `filter()`'s kwargs.

**A foreign key's own key column is selectable; the relation and anything past it are not.** `select(Post.author.id)` reads `"post"."author_id"` — a local column of the table being selected, with no join — so it is accepted, and it compiles to exactly what `values_list("author", flat=True)` always has. The rule is narrow: one hop, ending at the related model's primary key.

```python
author_ids = Post.query.select(Post.author.id, flat=True)
authors = Author.query.where(Author.id.is_in(author_ids))
```

With `result_type=`, the dataclass field is named for the column it holds — `author_id`, not the relation and not the `author__id` lookup path.

Everything else still raises `TypeError`:

- `select(Post.author)` — a relation is not a column. The message names the key column that is one.
- `select(Post.author.city)` — one hop, but the column lives on the other table.
- `select(Post.author.organization.id)`, or any hop through a many-to-many — the key column isn't local to the selecting table either.

The reason is nullability: a column reached over a join comes back as `None` when the relation doesn't match, and the traversed field's type says it can't. `values_list()` with the lookup path remains the spelling for those, and the error message names it. The key column has no such problem — its nullability is the foreign key's own `allow_null`.

One caveat on that: a nullable foreign key's key column types as `int`, not `int | None`. `Post.author` resolves to `type[Author]` at class access whether or not the foreign key is nullable — that is what makes traversal type-check at all — so `.id` is `Author`'s own `Field[int]` either way, and the nullability is lost before `select()` sees it. The value really can be `None`, so narrow it when the foreign key is nullable.

**`select()` hands back a plain `RowQuerySet`, not your custom QuerySet subclass.** Chain your own methods before `select()`, not after — `User.query.active().select(...)` works, `User.query.select(...).active()` raises `AttributeError`.

### Custom QuerySets

You can customize [`QuerySet`](./query.py#QuerySet) classes to provide specialized query methods. Define a custom QuerySet and assign it to your model's `query` attribute as a `ClassVar` (so it isn't treated as a constructor field):

```python
from typing import ClassVar, Self
from plain.postgres import Field, types


class PublishedQuerySet(postgres.QuerySet["Article"]):
    def published_only(self) -> Self:
        return self.filter(status="published")

    def draft_only(self) -> Self:
        return self.filter(status="draft")


@postgres.register_model
class Article(postgres.Model):
    title: Field[str] = types.TextField(max_length=200)
    status: Field[str] = types.TextField(max_length=20)

    query: ClassVar[PublishedQuerySet] = PublishedQuerySet()


# Usage - all methods available on Article.query
all_articles = Article.query.all()
published_articles = Article.query.published_only()
draft_articles = Article.query.draft_only()

# Chaining works naturally
recent_published = Article.query.published_only().order_by("-created_at")[:10]
```

For internal code that needs to create QuerySet instances programmatically, use `from_model()`:

```python
special_qs = SpecialQuerySet.from_model(Article)
```

### Typing QuerySets

`Model.query` is typed automatically — `User.query.get()` returns a `User` and
`User.query.filter()` returns `QuerySet[User]` with no extra annotation. Don't
redeclare `query` just to type it; the base provides `QuerySet[Self]`. Declare
`query` only when attaching a **custom** QuerySet, and then as a `ClassVar`
(see [Custom QuerySets](#custom-querysets) above).

### Written queries with sql()

A query is either **built** or **written**. The ORM builds one when the code assembles it at runtime — `where()`, `order_by()`, a paginator, a filter that's only sometimes applied. You write one when the whole query is known as you type it, however complex: a grouped count, a three-table join, a CTE, an `UPDATE ... RETURNING`. **If you can write the query, write it; if the code has to build it, build it.**

`Model.query.sql()` is the written half:

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass
class QueueStats:
    queue: str
    n: int
    oldest: datetime | None


stats = JobRequest.query.sql(
    """
    SELECT {JobRequest.queue} AS queue,
           count(*) AS "n!",
           min({JobRequest.created_at}) AS "oldest?"
    FROM {JobRequest}
    WHERE {JobRequest.queue} = ANY({queues})
    GROUP BY 1
    """,
    queues=["default", "high"],
    result_type=QueueStats,
)

for row in stats:
    print(row.queue, row.n)
```

The call renders the statement; iterating it runs it. `all()`, `get()`, `first()`, `count()`, `exists()` and `execute()` are the other ways to run one — `get()` raises the model's `DoesNotExist`/`MultipleObjectsReturned` when the statement returns instances, and a plain `ValueError` when it returns `result_type` rows — and it runs on the same connection and transaction as every other query. A statement runs **once**: its rows are cached, the way a queryset caches results, so iterating twice can't repeat a write. Call `sql()` again to run it again.

`sql()` starts from `Model.query`. A queryset narrowed past that — `where()`, `order_by()`, a slice — raises, because a written statement can't carry the narrowing and quietly dropping it would drop whatever the filter was enforcing. Put the queryset into the statement as a subquery instead. A model whose _default_ queryset filters can still write SQL, but that scope is **not** applied either: write the predicate into the statement, or embed `Model.query` as `{rows}`.

#### Interpolation

Everything in a template that isn't SQL is a `{}` reference, and what it names decides what it renders as. Values never go into the SQL text — they bind as parameters — so there is never an f-string.

| Reference                                             | Renders as                                                                      |
| ----------------------------------------------------- | ------------------------------------------------------------------------------- |
| `{Model}`                                             | the table, quoted                                                               |
| `{Model.field}`                                       | the qualified column, `"table"."column"` (a foreign key gives its `_id` column) |
| `{Model.field:name}`                                  | just the column, for an `INSERT` column list or an `UPDATE SET` target          |
| `{Model.*}`                                           | every column of the model; rows come back as **model instances**                |
| `{name}` where the value is a queryset                | `(SELECT ...)` — the built query as a subquery, its parameters merged           |
| `{name}` where the value is another `sql()` statement | the same, rendered without running                                              |
| `{name}` where the value is a `Fragment`              | inlined SQL text                                                                |
| `{name}` otherwise                                    | a bound parameter, always                                                       |

A value referenced twice binds twice. **A list binds as an array, never as an `IN` list**, so membership is written `= ANY(...)`:

```python
Widget.query.sql(
    "SELECT {Widget.*} FROM {Widget} WHERE {Widget.id} = ANY({ids})",
    ids=[1, 2, 3],
)
```

A dict binds as `jsonb`, ready for `@>`, `->` and the rest.

A `{` that isn't a reference — a regex quantifier like `\d{2}`, a jsonb or array literal — is written `{{`, and `}` is written `}}`, the same as any format string.

A queryset goes in as a subquery, which is the seam between the two halves — the built query decides the rows, the written one does what the ORM can't say:

```python
ready = JobRequest.query.ready_to_run()

JobRequest.query.sql(
    """
    SELECT ready.queue AS queue, count(*) AS "n!"
    FROM {ready} ready
    GROUP BY 1
    """,
    ready=ready,
    result_type=QueueCount,
)
```

A [`Fragment`](./written.py#Fragment) is the only way to put text into a statement that the template doesn't spell out:

```python
from plain.postgres import Fragment

ACTIVE = Fragment("status = 'active' AND deleted_at IS NULL")
```

**Templates and fragments are literals, written at the call site.** A template built at runtime — an f-string, a concatenation, a value passed in — puts the injection guarantee back in the caller's hands, and at runtime it is indistinguishable from a literal. So the rule is checked by reading the source: `plain preflight` walks the app and reports each one (`postgres.sql_template_not_literal`).

A _name_ is never accepted, however it was bound — following one would mean tracking every way Python can rebind it, and missing one is a false pass on the thing the check exists for. To share a predicate, share a `Fragment`, which is checked where its text is written:

```python
ACTIVE = Fragment("status = 'active' AND deleted_at IS NULL")  # checked here
```

A whole template is written where it's used.

An unknown model or field name, a `{name}` with no value, and a format spec on something that doesn't take one all raise where the `sql()` call is written, before anything runs. So does a second statement: whenever the statement binds a parameter Postgres enforces one command per statement (that's the protocol a written query goes over), and a template with nothing to bind is checked for a `;` here instead. A trailing `;` is dropped either way.

#### Results

`{Model.*}` gives live model instances, with encrypted and JSON fields decrypted and parsed like any other read. The instance is built from the columns that expansion put in the statement, so a self-join or a UNION can't shift its fields. Any other column you select comes back as a plain attribute on the instance, the way `raw()` does:

```python
widgets = Widget.query.sql(
    """
    SELECT {Widget.*}, count(wt.id) AS tag_count
    FROM {Widget}
    LEFT JOIN {WidgetTag} wt ON wt.widget_id = {Widget.id}
    GROUP BY {Widget.id}
    """
)
for widget in widgets:
    print(widget.name, widget.tag_count)
```

An extra column that shares a name with one of the model's own has to be aliased apart — otherwise it would overwrite the instance's value, and the statement says so. `prefetch()` works on an instance statement exactly as it does on a queryset.

Otherwise `result_type=` is required, and it has to be a dataclass — no dicts, no bare tuples. It also _is_ the answer to what a row is, so a `{Model.*}` below it — inside a subquery, say — is just columns. Columns map to its fields **by name**, so the order you select in doesn't matter. A field the statement doesn't select is an error unless it has a default; a column no field matches always is.

The sqlx alias convention says in the statement what the SQL itself leaves ambiguous: `AS "n!"` for "this is never null" and `AS "oldest?"` for "this can be". The marker is stripped before the column maps onto a field, so `count(*) AS "n!"` fills `n`. Today it is documentation — nothing enforces it — and nullability comes from the annotation.

#### Writes

`INSERT`, `UPDATE` and `DELETE` are the same call. With a `RETURNING` clause the rows come back like any other result; without one, iterating yields nothing and `execute()` returns how many rows were affected:

```python
updated = Widget.query.sql(
    """
    UPDATE {Widget} SET {Widget.size:name} = {size}
    WHERE {Widget.id} = {id}
    RETURNING {Widget.*}
    """,
    size="large",
    id=widget.id,
).get()

gone = Widget.query.sql(
    "DELETE FROM {Widget} WHERE {Widget.size} = {size}", size="tiny"
).execute()
```

`execute()` never shapes rows, so a write that returns columns you don't want to map is still runnable that way. A write runs exactly once however it's asked — `count()` and `first()` on one read what that single execution returned rather than running it again, and adding a `prefetch()` afterwards doesn't re-run it. Asking a write with no `RETURNING` clause how many rows it _returns_ raises: 0 would read like "the UPDATE matched nothing", and `execute()` is the question with an answer.

A violated check, unique or foreign key constraint raises the same `ValidationError` a model write raises, looked up by the constraint name across every model — a written statement can write any table. Where the ORM's message would name the offending value, a written one can't: it has rows, not instances.

#### What Postgres checks, and when

The first execution of each statement reads `cursor.description`, which carries every result column's name, type OID, and source table and column. That is enough to do two things, and the result is cached per set of result columns — so the cost is one extra catalog query the first time a shape is seen, and nothing after:

- **Attach field converters.** A column that traces back to a model column — through table aliases, column aliases, joins, derived tables and CTEs — is decrypted, parsed, or converted exactly as the ORM would. An expression, an aggregate and a UNION branch drop that trace, and a column with no trace comes back as Postgres sent it. A text-shaped one is watched: any value that arrives still encrypted is refused rather than handed back as ciphertext, since nothing can decrypt it. (Checked on every row of every execution, so a plain column holding a string that looks encrypted is refused too — which is the safe way to be wrong.)
- **Check `result_type`.** Every column needs a field of that name, every field a column, and the column's Python type has to match the annotation with `None` stripped. A mismatch raises `TypeError` printing the dataclass it expected.

The cached plan is only reused when the statement comes back with exactly the columns it was built from, so the same template with a different embedded queryset is checked again rather than hydrated from the wrong plan.

What it does **not** check: **nullability** — the annotation is the declaration, and `!`/`?` documents it. And the check runs at first execution, not before deploy, so a statement no test and no code path ever runs is unverified.

### Raw SQL

For complex queries that can't be expressed with the ORM, you can use raw SQL. Reach for [`sql()`](#written-queries-with-sql) first — it resolves `{}` references against the models, binds every value as a parameter, and checks the results against what you declared. `raw()` is the unchecked version of the same idea.

Use `Model.query.raw()` to execute raw SQL and get model instances back:

```python
users = User.query.raw(
    """
    SELECT * FROM users
    WHERE created_at > %s
    ORDER BY created_at DESC
""",
    [some_date],
)

for user in users:
    print(user.email)  # Full model instance with all fields
```

Raw querysets support `prefetch()` for loading related objects:

```python
users = User.query.raw("SELECT * FROM users WHERE is_admin = %s", [True])
users = users.prefetch("posts")
```

For queries that don't map to a model, use the database cursor directly:

```python
from plain.postgres import get_connection

with get_connection().cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = %s", [True])
    count = cursor.fetchone()[0]
```

For SQL set operations (UNION, INTERSECT, EXCEPT), use raw SQL. For simple cases, use Q objects instead:

```python
from plain.postgres import Q

# Equivalent to UNION (on same model)
users = User.query.filter(Q(is_admin=True) | Q(is_staff=True))
```

### Avoiding N+1 queries

#### Use `join()` for ForeignKey access in loops

Accessing a FK in a loop without `join()` fires one query per row.

```python
# Bad — N+1 queries
for post in Post.query.all():
    print(post.author.name)

# Good — single JOIN
for post in Post.query.join("author").all():
    print(post.author.name)
```

#### Use `prefetch()` for reverse/M2N access in loops

Reverse ForeignKey and ManyToMany relations need a separate prefetch query.

```python
# Bad — N+1 queries
for author in Author.query.all():
    print(author.posts.count())

# Good — one extra query
for author in Author.query.prefetch("posts").all():
    print(author.posts.count())
```

#### Annotate instead of per-row aggregations

Use database-level aggregation instead of calling `.count()` or similar per row.

```python
# Bad — N+1 queries
for category in Category.query.all():
    print(category.products.count())

# Good — single query with annotation
from plain.postgres.aggregates import Count

for category in Category.query.annotate(num_products=Count("products")).all():
    print(category.num_products)
```

#### Fetch all data in the view

Templates should only render data, never trigger queries. Prepare everything in the view.

```python
# Bad — template triggers lazy queries
def get_template_context(self):
    return {"posts": Post.query.all()}  # related lookups happen in template


# Good — eagerly load everything
def get_template_context(self):
    return {"posts": Post.query.join("author").prefetch("tags").all()}
```

### Query efficiency

#### Use `.values_list()` when you only need specific columns

```python
# Bad — loads entire model objects
emails = [u.email for u in User.query.all()]

# Good — single column, flat list
emails = list(User.query.values_list("email", flat=True))
```

#### Use `.exists()` instead of `.count() > 0`

`.exists()` stops at the first match; `.count()` scans all matching rows.

```python
# Bad
if User.query.filter(is_active=True).count() > 0:
    ...

# Good
if User.query.filter(is_active=True).exists():
    ...
```

#### Use `.count()` instead of `len(queryset)`

`len()` loads all objects into memory just to count them.

```python
# Bad
total = len(User.query.all())

# Good
total = User.query.count()
```

#### Use `bulk_create` / `bulk_update` for batch operations

Avoid calling `.create()` in a loop — each call is a separate query.

```python
# Bad — N INSERT statements
for name in names:
    Tag(name=name).create()

# Good — single INSERT
Tag.query.bulk_create([Tag(name=name) for name in names])
```

`bulk_create` is insert-only. To insert new rows and update the ones that
already exist in a single statement, use `bulk_upsert` (below).

#### Use `bulk_upsert` to insert-or-update in one statement

`bulk_upsert(objs, *, update_fields, unique_fields, batch_size=None)` issues one
`INSERT ... ON CONFLICT (unique_fields) DO UPDATE SET ... RETURNING` per batch.
Rows that don't exist yet are inserted; rows that collide on `unique_fields` have
their `update_fields` overwritten. You get back the objects you passed in, in the
order you passed them (a new list — `objs` itself is never reordered), each with
its DB-generated fields (primary key, DB defaults) populated.

```python
# Insert new items, refresh `value`/`expires_at` on any existing key.
CachedItem.query.bulk_upsert(
    [CachedItem(key=k, value=v, expires_at=exp) for k, v in items],
    update_fields=[CachedItem.value, CachedItem.expires_at],
    unique_fields=[CachedItem.key],
)
```

- `update_fields` and `unique_fields` take field references (`Model.field`), not
  strings. A foreign key is named by the relation itself — `Model.tenant`, which
  resolves to the `tenant_id` column. (This is the one write API that takes
  `Model.fk`. `returning()` refuses it, because there it would be ambiguous with
  asking for the whole related object; here a column list can only mean the
  column.)
- `unique_fields` must name the **primary key** or a `UniqueConstraint` declared
  on the model (no condition, no expressions) — this is the conflict target. A
  unique `Index` is not enough; declare a `UniqueConstraint`.
- `update_fields` must be concrete, non-primary-key, must not name the same
  column twice (Postgres assigns each column once per statement), and must not
  overlap `unique_fields`. A column the database fills in (`create_now`,
  `generate=True`, `RandomStringField`) can't be named either — the update would
  overwrite the stored value with a freshly evaluated default.
- Every object must have a non-null value for every unique field. `NULL` never
  conflicts in Postgres, so it can't be upserted. A database-generated column
  (`create_now`, `generate=True`, `RandomStringField`) can't be a unique field
  either — your objects never hold its value, so it could never conflict. Nor
  can an `update_now=True` column, which is stamped again on every write.
- **Two objects with the same unique key in one batch raise `ValueError`.**
  Postgres won't touch a row twice in one statement. Split across batches it's
  allowed — the first inserts, the second updates, and the later write wins.
- **`update_now=True` columns are refreshed on a conflict automatically.** You
  don't name them in `update_fields`; a row that gets updated gets a fresh
  stamp, and the object handed back carries the same one.
- **An `id` you set is kept on the insert path; on a conflict the stored row
  wins.** A new row is written with the `id` you gave it. A conflicting one
  already has an `id`, and that is the one hydrated back onto your object — the
  row in the table is the truth. An `id` that collides with a _different_ row
  raises `psycopg.errors.UniqueViolation`, like any set-based write.
- Every object is sorted by its conflict key before anything is sent, so
  concurrent `bulk_upsert` calls over overlapping keys lock rows in the same
  order and can't deadlock each other. Returned rows are mapped onto the objects
  by position, exactly as `bulk_create` does.
- Like `bulk_create`, the write is against the table: a filter on the queryset
  you call it from doesn't narrow or exclude anything.

For a single row, reach for `upsert` (below) instead — it returns the object and
a `created` flag rather than a list.

#### Use `upsert` for a single insert-or-update

`upsert(*, unique_fields, defaults=None, create_defaults=None, conflict_defaults=None, **kwargs)`
is the single-row counterpart to `bulk_upsert`. It runs one
`INSERT ... ON CONFLICT (unique_fields) DO UPDATE SET ... RETURNING` statement and
returns `(obj, created)` — `created` is `True` when a new row was inserted,
`False` when the conflicting row was updated. The object is hydrated from the
post-write row, so there's no second query.

```python
# Insert the flag, or refresh used_at on the existing one.
flag, created = Flag.query.upsert(
    name="beta-dashboard",
    defaults={"used_at": timezone.now()},
    unique_fields=[Flag.name],
)
```

`unique_fields` takes field references (`Model.field`), like `bulk_upsert`. The
value sources below stay string-keyed — they follow the `kwargs` idiom.

Value sources, lowest precedence first — where the same key appears in two of
them, `create_defaults` loses to `defaults`, which loses to `**kwargs`:

- `create_defaults` is applied on **insert only** — extras that must not change
  when the row already exists.
- `defaults` and `**kwargs` are applied on **both** insert and conflict-update.
  `kwargs` carries the identifying values (including the unique fields).
- `conflict_defaults` applies to the `DO UPDATE SET` **only** — it never changes
  the inserted row. A value can be a plain value or an expression, so
  `{"count": F("count") + 1}` is an atomic counter that reads the existing row:

```python
view, created = PageView.query.upsert(
    path="/home",
    conflict_defaults={"count": F("count") + 1},
    unique_fields=[PageView.path],
)
```

Two expressions reach two different rows inside a conflict update. `F("count")`
reads the row already **stored**; `Excluded("count")` reads the row the INSERT
**proposed**, compiling to `EXCLUDED."count"`. Combine them to accumulate the
incoming value instead of overwriting it — the whole statement is one atomic
`UPDATE`, so concurrent callers each add their own delta:

```python
from plain.postgres import Excluded, F

# Add this batch's 7 views to whatever is already stored.
view, created = PageView.query.upsert(
    path="/home",
    count=7,
    conflict_defaults={"count": F("count") + Excluded("count")},
    unique_fields=[PageView.path],
)
```

`Excluded()` is only meaningful while the conflict update's assignments are
being built. Anywhere else raises a `FieldError` — including as an inserted
value in `kwargs`/`defaults`/`create_defaults` of the very same call, where it
would be naming the row being written, and in `filter()`, `update()` or
`annotate()`.

On conflict the `SET` clause covers:

- every non-unique, non-PK column from `kwargs`/`defaults`, each taking the value
  the INSERT proposed;
- every `DateTimeField(update_now=True)` column, whose fresh `pre_save()`
  timestamp rides along in the INSERT and would otherwise go stale (a
  `create_now`-only column is _not_ in the `SET`, so it keeps its original
  value);
- every column `conflict_defaults` names — replacing the proposed value when the
  column is already in the `SET`, adding it when it isn't.

Columns nobody wrote are left alone, and `create_defaults` never take part in the
update. Naming a **database-owned** column (`create_now`, `generate=True`,
`RandomStringField`) in `kwargs`/`defaults` is an error rather than a silent
reset: `EXCLUDED` carries a freshly evaluated default, so the conflict update
would overwrite the stored creation timestamp every time. A column that's also
`update_now` is exempt — refreshing it is the point. Unlike `bulk_upsert`, `upsert` derives its `SET` columns rather than
taking them, so a `conflict_defaults` key may not name a unique field — that's
the conflict target.

Every value source resolves callables, and every key must name a **column** — a
settable property is refused, since the `SET` clause is derived from columns and
a property could only ever be written on the insert half.

`unique_fields` must name a `UniqueConstraint` declared on the model (no
condition, no expressions) and every unique field must be non-null. It can't be
the primary key: Postgres generates the identity value, so a caller has nothing
to conflict on.

Three things to keep in mind:

- **`kwargs` are values, not filters.** A keyword that isn't part of the conflict
  key doesn't narrow which row is matched — `unique_fields` alone decides that —
  it's just another column written to whichever row conflicts.
- **The queryset's filters don't scope it either.** `qs.filter(...).upsert(...)`
  writes the conflicting row whether or not it matches the filter — the conflict
  constraint decides which row is touched. It isn't refused because the
  related-manager wrappers call through a filtered queryset. To scope an upsert,
  fold the scoping column into `unique_fields` (and into the constraint), or do a
  locked read and write instead.
- **The merged row isn't validated**, and a constraint violation surfaces as a raw
  `psycopg.IntegrityError`, not a `ValidationError`. `upsert` looks single-row
  like `create()`, but it's a set-based write like `bulk_upsert` (see
  [Validation](#validation)).

#### Use queryset `.update()` / `.delete()` for mass operations

```python
# Bad — N UPDATE statements
for user in User.query.filter(is_active=False):
    user.is_archived = True
    user.update()

# Good — single UPDATE statement
User.query.filter(is_active=False).update(is_archived=True)
```

#### Use `.only()` / `.defer()` for heavy columns

Skip large text or JSON fields when you don't need them.

```python
# Bad — loads large body text for a listing page
posts = Post.query.all()

# Good — defers heavy column
posts = Post.query.defer("body").all()
```

Reading any deferred field on an instance loads every still-missing column in a single query, not just the field you asked for. Defer columns you don't intend to access on that instance, and prefer `.values()` / `.values_list()` when you want one column without ever materializing the rest. The foreign key column is the exception: accessing a deferred foreign key loads only the foreign key column, so the partial-related-instance shortcut stays cheap.

#### Use `.iterator()` for large result sets

Process rows in chunks instead of loading everything into memory.

```python
# Bad — entire table in memory
for row in HugeTable.query.all():
    process(row)

# Good — chunked iteration
for row in HugeTable.query.iterator(chunk_size=2000):
    process(row)
```

## Returning affected rows

`QuerySet.update()` and `QuerySet.delete()` return an `int` rowcount. Chain `returning()` before the write to get the affected rows back instead — Postgres' `RETURNING` clause fetches them in the same statement, so there's no second query.

```python
# No arguments: rows come back as model instances.
running = Job.query.filter(status="pending").returning().update(status="running")
for job in running:
    print(job.id, job.status)  # reflects the post-update values

# Field references: rows come back as dicts of just those columns.
deleted = (
    Event.query.filter(created_at__lt=cutoff)
    .returning(Event.id, Event.payload)
    .delete()
)
for row in deleted:
    print(row["id"], row["payload"])  # the rows as they were deleted
```

- **`returning()`** returns full model instances. For `update()` they hold the new values and stay live. For `delete()` they are **read-only snapshots**: every value is there to read, the id included, but the row is gone, so `create()`, `update()` and `delete()` on them raise.
    - That is the opposite of `Model.delete()`, which clears the instance's id and leaves it re-creatable — that instance is a row you still hold and may want to put back, while a snapshot is a record of one that was removed, and its id is the point.
- **`returning(Model.field, ...)`** returns a list of dicts with only those columns. Pass field references (`Model.field`), not strings; a many-to-many field or one from another model raises an error at the `returning()` call.
- **A foreign key can't be named here.** At class level `Model.fk` is the relation — that is what lets `where()` traverse it, as in `Child.parent.name.equals(...)` — not its column, so `returning(Child.parent)` raises `FieldError`. Foreign key columns come back through no-argument `returning()`, which hands you whole instances.
- Without `returning()`, `update()`/`delete()` return an `int` as before.
- `returning()` only applies to `update()` and `delete()`. Any other write on the same queryset — `create()`, `bulk_create()`, `bulk_upsert()`, `bulk_update()`, `get_or_create()`, `upsert()` — raises `TypeError` rather than quietly dropping it.
- `returning()` keeps the queryset's own class, so a custom `QuerySet` and its methods survive it. Chain your own methods before `returning()` — a type checker sees the returning shape after it, not your subclass.

A row lock belongs on the read side of the write, and it composes in either order. The write then needs an open `transaction.atomic()`, and is emitted as a locking sub-select so the lock has somewhere to live — see [Locking a set-based write](#locking-a-set-based-write).

`returning()` is inert for reads. It describes what the next `update()` or `delete()` hands back, so iterating, `count()`, `first()` and `values()` on the same queryset behave exactly as they would without it — which is what lets you inspect a chain before writing it.

The values you get back are whatever the statement wrote, exactly as Postgres holds them. A set-based `update()` doesn't run Python-side field hooks, so an `update_now=True` timestamp comes back unchanged unless the `update()` set it.

`RETURNING` only reports rows of the statement's own target table. Rows removed by a cascading `ON DELETE` are never included — a `delete()` with `returning()` gives you the parent rows you deleted, not the children Postgres cascaded.

Every affected row is fetched and built into memory at once, so `returning()` belongs on writes you've already bounded by a filter. For a write that spans a whole table, take the rowcount and page through the rows separately.

## Transactions

By default, each query runs in its own implicit transaction and is committed immediately (autocommit mode). When you need multiple queries to succeed or fail together — like creating a user and their profile — wrap them in an explicit transaction.

### Atomic blocks

Wrap multiple queries in a transaction with `transaction.atomic()`:

```python
from plain.postgres import transaction

with transaction.atomic():
    user = User(email="test@example.com")
    user.create()
    Profile(user=user).create()
    # Both writes commit together, or both roll back on error
```

Nesting `atomic()` creates savepoints:

```python
with transaction.atomic():
    user.create()
    try:
        with transaction.atomic():
            risky_operation()  # If this fails...
    except SomeError:
        pass  # ...only the inner block rolls back
    safe_operation()  # This still runs in the outer transaction
```

### Read-only transactions

Run a block of code in a read-only transaction using `read_only()`. Any write (INSERT, UPDATE, DELETE, DDL) raises `psycopg.errors.ReadOnlySqlTransaction`:

```python
from plain.postgres.db import read_only

with read_only():
    users = User.query.all()  # reads work
    User.query.create(name="x")  # raises psycopg.errors.ReadOnlySqlTransaction
```

`read_only()` opens a single `BEGIN READ ONLY` transaction for the block. Nested `atomic()` blocks inside become savepoints of the outer read-only transaction and inherit read-only.

Because it opens its own transaction, `read_only()` cannot be entered inside an existing `atomic()` block — doing so raises `TransactionManagementError`.

Because the whole block is one transaction, catching a database error inside `read_only()` and trying to keep reading will fail — the transaction is aborted and any further query raises `TransactionManagementError`. Wrap the write in a nested `atomic()` savepoint if you need to recover and continue:

```python
with read_only():
    try:
        with atomic():
            User.query.create(name="x")  # raises, savepoint rolls back
    except psycopg.errors.ReadOnlySqlTransaction:
        pass
    User.query.count()  # still works — outer txn is healthy
```

### Row-level locking

Lock the rows a query selects so concurrent transactions can't change them until yours commits. Postgres offers four lock strengths, from strongest to weakest, each with its own QuerySet method:

```python
with transaction.atomic():
    account = Account.query.for_update().get(id=1)  # FOR UPDATE
    account.balance -= 100
    account.update(fields=["balance"])
```

| Method                | SQL clause          | Use it when                                                                |
| --------------------- | ------------------- | -------------------------------------------------------------------------- |
| `for_update()`        | `FOR UPDATE`        | You intend to update or delete the row.                                    |
| `for_no_key_update()` | `FOR NO KEY UPDATE` | Same, but you won't touch the primary key — lets key-share locks proceed.  |
| `for_share()`         | `FOR SHARE`         | You need the row to stay put while you read it, but others may also share. |
| `for_key_share()`     | `FOR KEY SHARE`     | Weakest — only blocks changes to the row's key.                            |

Locking requires an open transaction. The method itself just builds the queryset — evaluating a locked queryset outside `transaction.atomic()` is what raises `TransactionManagementError`.

All four accept the same options:

- `nowait=True` — raise instead of waiting if a row is already locked.
- `skip_locked=True` — skip already-locked rows instead of waiting (can't be combined with `nowait`).
- `of=("self", "related")` — lock only the named tables in a join rather than every selected row.

```python
# Claim the next available job without blocking on rows another worker holds
job = Job.query.for_update(skip_locked=True).filter(status="pending").first()
```

Chaining more than one lock method keeps only the last one, options included.

Postgres can only lock rows that map one-to-one onto table rows, so a lock can't be combined with `distinct()`, an aggregate annotation, or a window annotation. Either order raises `psycopg.NotSupportedError` when the queryset is built, naming the lock method:

```python
Widget.query.distinct().for_update()  # NotSupportedError
Widget.query.for_update().distinct()  # same error, either way round
```

`count()` and `aggregate()` are the exception — they compile to an aggregate query of their own, so they drop the lock rather than reject it.

#### Locking a set-based write

A lock also applies to `update()` and `delete()` on the same queryset. Neither statement takes a locking clause of its own, so the write is emitted as a locking sub-select:

```python
# Claim *all* pending rows matching the filter, in one statement
with transaction.atomic():
    claimed = (
        Job.query.filter(status="pending")
        .for_update(skip_locked=True)
        .returning()
        .update(status="running")
    )
```

```sql
UPDATE "jobs" SET "status" = 'running'
WHERE "id" IN (
    SELECT U0."id" FROM "jobs" U0 WHERE U0."status" = 'pending' FOR UPDATE OF U0 SKIP LOCKED
)
RETURNING ...
```

It is still one statement. A second worker running the same write skips the rows the first one holds instead of blocking on them, so each row is claimed once.

Note what this is and isn't: it takes **every** row the filter matches, so it suits draining a batch, not handing one unit of work to one worker. A bounded claim would need a sliced write (`[:1]`), and `update()`/`delete()` reject a sliced queryset — so for a per-worker claim, take one row with the locked read above (`for_update(skip_locked=True)` + `first()`) and write it separately.

The `transaction.atomic()` is required, same as for a locked read: a locked write outside a transaction raises `TransactionManagementError`. Nothing else honors the lock — without a transaction there is nothing for it to be held until.

**A locked write locks only the target table's rows.** When the filter spans a relation, the sub-select joins the other tables to look values up, and a bare `FOR UPDATE` would lock a row in each of them — so a write whose filter reads a parent would wait on (or, with `skip_locked=True`, silently skip) rows it never touches. The clause is emitted as `FOR UPDATE OF <target>` so that can't happen. To lock related rows as well, take them with a separate locked read.

That is also why `of=` can only name `"self"` on a write: the sub-select reads one column — this table's id — so a related name has nothing to point at, and `update()`/`delete()` raise `TypeError` rather than let it fail deeper down. Dropping `of=` is the same thing; the write locks its own rows either way.

## Schema management

Schema changes fall into three categories, each with a different author and apply model:

- **Convergence** — declarative properties like indexes, constraints, NOT NULL, and FK `on_delete`. Derived from model definitions and applied automatically using online-safe DDL (`CREATE INDEX CONCURRENTLY`, `NOT VALID` + `VALIDATE`, etc.). The framework owns the safe apply pattern.
- **Structural migrations** — tables, columns, renames, column type changes. Framework-generated from the model diff, but you review them and decide when to deploy (a column type change can rewrite the table; a column drop is destructive).
- **Data migrations** — backfills, transformations, one-time cleanup. Authored by you via `RunPython` or `RunSQL`. The framework only sequences them.

| Change                                | Category             | Safe apply pattern                                  |
| ------------------------------------- | -------------------- | --------------------------------------------------- |
| Add / drop index                      | Convergence          | `CREATE INDEX CONCURRENTLY`                         |
| Add / drop unique or check constraint | Convergence          | `ADD CONSTRAINT NOT VALID` + `VALIDATE`             |
| Add / remove NOT NULL                 | Convergence          | `CHECK NOT VALID` + `VALIDATE` + `SET NOT NULL`     |
| Change FK `on_delete` action          | Convergence          | drop + re-add with `NOT VALID` + `VALIDATE`         |
| Set / change / drop column `DEFAULT`  | Convergence          | catalog-only `ALTER COLUMN SET/DROP DEFAULT`        |
| Create / drop table                   | Structural migration | framework-generated, you review                     |
| Add / drop / rename column            | Structural migration | framework-generated, you review                     |
| Column type change (safe widening)    | Structural migration | framework-generated `ALTER TYPE` with implicit cast |
| Column type change (other)            | Data migration       | you author (explicit `RunSQL` with `USING`)         |
| Data backfill or transformation       | Data migration       | you author (`RunPython` / `RunSQL`)                 |
| One-time cleanup, seeding             | Data migration       | you author                                          |

**The principle: who authors the change, and can the framework guarantee safety?** If the framework can derive both the change and a universally-safe apply pattern from model definitions, it belongs to convergence. If the framework can generate the DDL but safety depends on context (table size, deploy timing, destructiveness), it's a structural migration — you review it before deploying. If only you know what to do, it's a data migration.

Many convergence-managed changes produce DB-enforced behavior — cascading deletes (`ON DELETE`), validation (`CHECK`, `NOT NULL`), default generation. Whether a change is "behavioral" doesn't determine the category; whether the framework can guarantee a safe apply does.

| Property                 | Convergence                                                           | Migrations                                                  |
| ------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------------- |
| Authored by              | Framework (derived from models)                                       | Framework (structural) or you (data)                        |
| When it runs             | Every `sync`, by diffing models vs database                           | Once, in recorded timestamp order                           |
| Drift correction         | Yes — reverts undeclared DB changes on next sync                      | No — manual DB changes persist                              |
| Reversible (intentional) | Implicit — roll back code, re-sync re-derives                         | No — forward-only, fix-forward                              |
| Failure behavior         | Per-operation commits — partial progress on failure (re-run to retry) | Batch transaction — failure rolls back the entire migration |
| Files on disk            | None — derived from models live                                       | `.py` files in `migrations/`                                |
| Safe DDL                 | Framework-applied patterns (CONCURRENTLY, NOT VALID + VALIDATE)       | Generated DDL; you review before deploy                     |

**Drift correction is a convergence-only behavior.** Convergence re-runs on every `sync` and compares models against the database. An index created manually outside a model declaration will be dropped on the next run because models are the source of truth. Migrations don't behave this way — once applied, they're recorded and never re-applied.

**Caveats.** The safety promise isn't absolute. Structural migrations aren't lint-checked yet: adding a column with a volatile default (`gen_random_uuid()`, `now()`) on a large table will rewrite it without warning. Review structural migrations before deploying to production.

**Column type changes.** The autodetector only auto-generates `AlterField` for a small allowlist of lossless widenings (`smallint → integer`, `smallint → bigint`, `integer → bigint`) and for parameter-only changes like `max_length`. Every other base-type change rejects with guidance — arbitrary `USING col::newtype` casts either fail at apply time (e.g. timestamp → uuid) or silently corrupt data (e.g. bigint FK → text stringifies PKs), and migrations are forward-only. For anything outside the allowlist, scaffold `plain migrations create --empty --name alter_<model>_<field>_type` and author an explicit `RunSQL` with a `USING` expression you've reviewed.

"Safe" here means data-integrity safe, not operationally cheap. An `ALTER COLUMN ... TYPE` that changes on-disk width (any of the allowlisted widenings) takes `ACCESS EXCLUSIVE` and rewrites the table — on a large table this can block writes for minutes. Deploy these during a maintenance window, not in the middle of traffic.

**Out of scope for convergence.** Triggers, views, stored procedures, and other non-standard DDL stay outside convergence — it won't create them from models, and it won't drop them if they exist. Manage them with `RunSQL` data migrations.

### Syncing

The primary command for all schema management is `postgres sync`. It runs migrations and convergence together:

```bash
plain postgres sync
```

```
plain postgres sync
│
├─ 1. Create migrations (development only)
│     Detects model changes, generates migration files
│
├─ 2. Apply migrations
│     Runs pending migrations in a single transaction
│
└─ 3. Converge
      Compares indexes, constraints, FKs, and nullability
      against model declarations — applies fixes independently
```

In development (`DEBUG=True`), sync auto-generates migrations before applying them. In production, it only applies existing migrations and converges.

| Command                        | Purpose                                                               |
| ------------------------------ | --------------------------------------------------------------------- |
| `plain postgres sync`          | Create + apply migrations + converge (the one command for everything) |
| `plain postgres sync --check`  | Exit non-zero if anything would change (for CI)                       |
| `plain postgres schema`        | Show schema state with drift detection                                |
| `plain postgres schema --json` | Machine-readable schema output                                        |
| `plain postgres converge`      | Run convergence alone (advanced)                                      |

### Structural migrations

Structural migrations are framework-generated from model changes — tables, columns, renames, column type changes. They are Python files stored in your app's `migrations/` directory. You don't author them by hand; you edit models and run `plain migrations create`.

```bash
plain migrations create
```

Key flags:

- `--dry-run` — Show what migrations would be created (with operations and SQL) without writing files
- `--check` — Exit non-zero if migrations are needed (for CI)
- `--name <name>` — Set the migration filename

Shared commands (apply equally to structural and data migrations):

| Command                            | Purpose                                                           |
| ---------------------------------- | ----------------------------------------------------------------- |
| `plain migrations apply`           | Apply pending migrations                                          |
| `plain migrations apply --plan`    | Preview what would run                                            |
| `plain migrations apply --check`   | Exit non-zero if unapplied migrations exist (for CI)              |
| `plain migrations apply --fake`    | Mark as applied without running SQL                               |
| `plain migrations list`            | View migration status by package                                  |
| `plain migrations prune`           | Remove orphan migration records                                   |
| `plain migrations prune <package>` | Remove every record for one package (lets its baseline run again) |
| `plain migrations reset <package>` | Replace the package's history with one baseline                   |

#### Development workflow

During development, iterating on models often produces multiple small migrations (0002, 0003, 0004...). Clean these up before committing.

**Consolidating uncommitted migrations (delete-and-recreate):**

Use this when migrations exist only in your local dev environment and haven't been committed or deployed.

1. Delete the intermediate migration files (keep the initial 0001 and any previously committed migrations)
2. `plain migrations prune --yes` — removes stale DB records for the deleted files
3. `plain migrations create` — creates a single fresh migration with all the changes
4. `plain migrations apply --fake` — marks the new migration as applied (the schema is already correct from the old migrations)

Migrations that are committed but not yet deployed anywhere can be consolidated the same way if every developer resets their database; production then applies the consolidated migration normally. Once a migration has reached any deployed environment, use a full reset (below).

#### Baselines

A package whose migration history has been reset ships one **baseline** migration in place of the deleted files. It is an ordinary migration with three extra attributes:

```python
class Migration(migrations.Migration):
    supersedes = "0008_add_widgets"  # the sentinel: the last deleted migration; its record proves a database is caught up
    retired = (
        "0001_initial",
        ...,
        "0008_add_widgets",
    )  # every deleted name, so dependencies on them still resolve
    shipped_in = "0.61"  # the release that shipped the reset; empty until it has
    dependencies = (("users", "0001_initial"),)
    operations = (migrations.CreateModel(...), ...)
```

What `plain postgres sync` (or `plain migrations apply`) does with it depends only on what the database has recorded:

| Database has                                                      | Result                                                                                                 |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| No records for the package, no tables (fresh, or newly installed) | Runs the baseline like any migration                                                                   |
| No records for the package, but its tables exist                  | Refuses: record it with `apply <pkg> <baseline> --fake` if the schema is current, else drop the tables |
| The baseline recorded                                             | Nothing                                                                                                |
| The `supersedes` migration recorded                               | Records the baseline without running it - one row, once                                                |
| Records, but not the `supersedes` migration                       | Refuses: upgrade through the last release that still has that migration                                |
| Records, but none of the package's tables                         | Refuses: `plain migrations prune <pkg>` drops the records; then it runs                                |

`plain migrations apply --plan --check` and `plain postgres sync --check` report a baseline waiting to be recorded as a pending change, and `plain preflight` reports a refusal as an error. Nothing ever deletes records on its own; `prune` stays explicit. A database where the baseline _ran_ (rather than was recorded) cannot roll back to code from before the reset.

#### Resetting migrations

Once **every environment** has applied a package's migrations, its history can be collapsed into one baseline:

```bash
plain migrations reset <package>
```

The command writes `NNNN_baseline.py` past the current leaf (the package's newest migration) — the package's schema as `CreateModel`s, `supersedes` set to the leaf, `retired` set to every deleted name — and deletes the old files. Commit the new file and the deletions together. Existing databases adopt it with one record on their next `plain postgres sync`; the retired records stay as the rollback path; a fresh database runs it. Other packages' migrations that depended on a deleted name resolve to the baseline; nothing there needs rewriting. Do not add a `prune` step. Before it touches anything it checks, in this order:

- The models agree with the history (`plain migrations create` would write nothing). A change the history doesn't hold would be folded into the baseline, and databases that adopt it would never run it.
- The package ends in a single leaf, and no earlier baseline is waiting unreleased (see second resets below).
- The deleted history holds nothing a fresh database would miss. `RunPython`, `RunSQL`, any custom operation, and anything on the database side of `SeparateDatabaseAndState` are listed and refused until each carries `skip_on_reset=True` — "a fresh database can do without this." If it can't (a seed, an extension), move the effect somewhere a fresh database does get it, then mark it.
- The migrations directory is committed — tracked, unmodified, inside a git repository (so an installed package in site-packages cannot be reset; the check applies to `--dry-run` too). The leaf becomes the baseline's sentinel, so it cannot be something you created a minute ago. No check can prove every environment applied it — the command prints that obligation, and a database that hasn't is refused until it does. If anything goes wrong the output has already printed the one line that puts it back: `git checkout -- <migrations dir> && rm <the new baseline>`.
- The result loads: dependencies on retired names resolve, the graph has no cycle, the baseline reproduces the models exactly.
- Nothing the baseline needs is defined inside a migration file. A custom field class or callable written in the history disappears with it; move it into the app first.

Options:

- `--shipped-in <version>` — the release this reset ships in, named in the refusal a database that missed the leaf gets, and required before the package can be reset again. Plain's own packages leave it empty and fill it in at release time (a repository test enforces it, and the package's `plain.postgres` minimum is raised to the first release that understands baselines); an app should pass the version or deploy this ships in.
- `--dry-run` — print the baseline and the deletion list, write nothing.

**Dependencies.** The baseline depends on each other package its models reference, at the earliest migration of that package where the referenced models exist — and on nothing else. A package that another package pinned early _and_ whose models now point back at that package cannot get a single root: the graph would be a cycle, and the command refuses with it. That is a limit of migration graphs, not of the command; nothing to do with a second package fixes it.

**Support boundaries.** Adoption checks that the sentinel is recorded and the tables exist, not columns; editing history behind a released leaf is outside what any check can catch. A data migration in _another_ package that read this package's historical state (a field the baseline no longer has) keeps loading but can fail on a fresh database; the command cannot see it.

**Second reset.** Run it again later and the previous baseline joins `retired`. It refuses while the previous baseline's `shipped_in` is empty: nothing shipped it yet, so superseding its name would strand every database still at the original sentinel — once that baseline has shipped everywhere, set its `shipped_in` to the version that shipped it and reset again; otherwise restore the history and reset once.

### Data migrations

Data migrations are user-authored operations — backfills, transformations, seeding, cleanup. The framework has no way to derive these from models; you write the logic and it gets sequenced in timestamp order alongside structural migrations.

Create an empty migration to author one:

```bash
plain migrations create --empty <package>
```

Add a `RunPython` or `RunSQL` operation inside:

```python
def forwards(models, schema_editor):
    User = models.get_model("users", "User")
    # Use .update() for batch SQL — a row-by-row save loop can lock a large table.
    User.query.filter(full_name="").update(full_name="pending")
```

For large tables, chunk the work (e.g. by ID range) and commit between batches so no single transaction holds locks for too long.

When the package's history is later collapsed (see [Resetting migrations](#resetting-migrations)), `plain migrations reset` refuses while any `RunPython`/`RunSQL` is unmarked. Pass `skip_on_reset=True` once a fresh database can do without its effect; if it can't, move the effect into a seed first.

See [Structural migrations](#structural-migrations) for shared commands (`apply`, `list`, `prune`).

#### Cascading deletes inside data migrations

`Model.delete()` and `QuerySet.delete()` rely on Postgres `ON DELETE` clauses (`CASCADE`, `SET NULL`, `RESTRICT`) — Plain does not walk relationships in Python.

Foreign key constraints are added by **convergence** (step 3 of `postgres sync`), not by migrations. During a fresh `migrations apply` (before convergence has run), FK constraints don't exist yet. A `RunPython` data migration that calls `.delete()` on a model with cascading children will:

- Delete only the parent row — children become orphans
- Cause convergence's later `VALIDATE CONSTRAINT` step to fail because of the orphans

This only affects fresh applies. Existing databases keep their FK constraints across syncs, so incremental data migrations are unaffected.

**If your data migration needs to delete rows that have cascading children, handle the cascade explicitly:**

```python
def forwards(models, schema_editor):
    Parent = models.get_model("myapp", "Parent")
    Child = models.get_model("myapp", "Child")
    # Delete children first, then parent — explicit, no constraint reliance
    Child.query.filter(parent__name="old").delete()
    Parent.query.filter(name="old").delete()
```

Or use `RunSQL` with explicit cascade if the relationship is large.

### Convergence

Convergence compares the indexes, constraints, foreign keys, nullability, and [storage parameters](#storage-parameters) declared on your models against what actually exists in the database, then applies fixes to make them match. You don't need to create migrations for these — just declare them on your model and run `postgres sync`.

```python
@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    username: Field[str] = types.TextField(max_length=150)
    age: Field[int] = types.IntegerField()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(fields=["email"], name="users_email_idx"),
        ],
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="users_email_uniq"),
            postgres.CheckConstraint(
                check=postgres.Q(age__gte=0), name="users_age_positive"
            ),
        ],
    )
```

When you run `postgres sync`, convergence detects that these indexes and constraints are missing and creates them — using non-blocking DDL operations where possible (e.g. `CREATE INDEX CONCURRENTLY`, `ADD CONSTRAINT ... NOT VALID` followed by `VALIDATE CONSTRAINT`).

**Key properties:**

- **Idempotent** — safe to run repeatedly. If the database already matches, nothing happens.
- **Non-blocking** — indexes are built with `CONCURRENTLY`, constraints use `NOT VALID` + `VALIDATE` to avoid locking writes.
- **Per-operation commits** — each fix is committed independently so a single failure doesn't roll back other fixes.
- **Self-healing** — detects and rebuilds `INVALID` indexes (e.g. from a previously failed `CREATE INDEX CONCURRENTLY`).
- **Rename-aware** — detects renamed indexes and constraints by matching their structure, avoiding unnecessary drop + recreate.

**Inspecting schema state:**

Use `postgres schema` to see what convergence would do. It shows every model's columns, indexes, and constraints compared against the database, with issues highlighted:

```bash
plain postgres schema           # all models
plain postgres schema User      # single model
plain postgres schema --json    # machine-readable output
```

**Staged rollouts:**

Some changes can't be applied automatically. For example, if you add `NOT NULL` to a column that has existing `NULL` rows, convergence will report this as a blocked change and tell you to backfill the data first. Run `postgres sync` again after the backfill.

**Cleanup:**

When you remove an index or constraint from a model, convergence automatically drops the undeclared database object on the next `postgres sync`. Models are the source of truth — if it's not declared, it gets removed.

### DDL timeouts

Every framework-issued DDL statement — both in migrations and in convergence — is wrapped with `lock_timeout` and `statement_timeout` so a deploy can't hang indefinitely waiting for a lock, and so a backfill against an unexpectedly large table fails fast instead of holding `ACCESS EXCLUSIVE` for minutes.

```python
# app/settings.py — defaults shown
POSTGRES_MIGRATION_LOCK_TIMEOUT = "3s"
POSTGRES_MIGRATION_STATEMENT_TIMEOUT = "3s"
POSTGRES_CONVERGENCE_LOCK_TIMEOUT = "3s"
POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT = "3s"
```

`lock_timeout` applies to every DDL. `statement_timeout` applies only to statements that take `ACCESS EXCLUSIVE` — non-blocking operations (`CREATE INDEX CONCURRENTLY`, `VALIDATE CONSTRAINT`) run unbounded because they can't cascade the lock queue.

If a migration issues a row-touching UPDATE (e.g. a hand-written `RunPython` or `RunSQL` backfill), the 3s `statement_timeout` will kill it on any non-tiny table. That's intentional — the right fix is a batched data migration, not a single long-running UPDATE. The common first-time failure mode is applying migrations against a pre-seeded dev or staging database: raise the ceiling for that one run, then lower it back for production deploys.

Use `RunSQL(no_timeout=True)` to opt out for a specific operation:

```python
from plain.postgres.migrations.operations import RunSQL

operations = [
    RunSQL(
        "UPDATE orders SET status = 'pending' WHERE status IS NULL",
        no_timeout=True,
    ),
]
```

Non-atomic migrations (`Migration.atomic = False`, used for `CREATE INDEX CONCURRENTLY` in a migration) skip the timeout prelude automatically — `SET LOCAL` is a no-op outside a transaction block. Manage timeouts inside your own `RunSQL` if you need them.

Environment overrides: every setting accepts `PLAIN_POSTGRES_*` env vars, so you can raise the ceiling for a specific deploy without a code change:

```bash
PLAIN_POSTGRES_MIGRATION_STATEMENT_TIMEOUT=30s plain migrations apply
```

### Schema lock

Schema-changing commands — `plain postgres sync`, `plain migrations apply`, `plain postgres converge`, and `plain postgres drop-unknown-tables` — serialize on a single session-level advisory lock, so two deploy processes running at once (a retried migrate job, overlapping release phases) can't interleave schema changes. You don't have to do anything to get this.

A second process warns and waits, retrying until the holder finishes:

```python
# app/settings.py — defaults shown (waits up to an hour total)
POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL = 5.0
POSTGRES_SCHEMA_LOCK_MAX_RETRIES = 720
```

The wait is generous by default because a legitimate holder can be mid index build. If the budget runs out, the command fails with the holder's `pid` so you can see what's blocking. A crashed holder is not a problem — the lock releases automatically when its database session closes.

The lock is held on its own connection, separate from the one running DDL, so non-transactional operations (`CREATE INDEX CONCURRENTLY`, `VALIDATE CONSTRAINT`) work normally while it's held. Session-level locks don't survive transaction-mode poolers like pgbouncer — if your `POSTGRES_URL` points at one, set [`POSTGRES_MANAGEMENT_URL`](#bypassing-a-connection-pooler-for-management-operations) to a direct connection.

The lock connection sits idle while your DDL runs, so it enables TCP keepalives to survive NAT and load-balancer idle timeouts. A server-side `idle_session_timeout` would still kill it (releasing the lock mid-run) — don't set one for the role that runs migrations. `sync` re-verifies the lock between its migrate and converge phases and stops with a clear error if the session died.

To see the lock live: `SELECT * FROM pg_locks WHERE locktype = 'advisory' AND objid = 1047265496`.

## Fields

You can use many field types for different data:

```python
from decimal import Decimal
from datetime import datetime

from plain import postgres
from plain.postgres import Field, types


class Product(postgres.Model):
    # Text fields
    name: Field[str] = types.TextField(max_length=200)
    description: Field[str] = types.TextField()

    # Numeric fields
    price: Field[Decimal] = types.DecimalField(max_digits=10, decimal_places=2)
    quantity: Field[int] = types.IntegerField(default=0)

    # Boolean fields
    is_active: Field[bool] = types.BooleanField(default=True)

    # Date and time fields
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(update_now=True)
```

**Text fields:**

- [`TextField`](./fields/__init__.py#TextField) - Text (with optional max length)
- [`EmailField`](./fields/__init__.py#EmailField) - Email address (validated)
- [`URLField`](./fields/__init__.py#URLField) - URL (validated)

**Numeric fields:**

- [`IntegerField`](./fields/__init__.py#IntegerField) - Integer
- [`BigIntegerField`](./fields/__init__.py#BigIntegerField) - Big (8 byte) integer
- [`SmallIntegerField`](./fields/__init__.py#SmallIntegerField) - Small integer
- [`FloatField`](./fields/__init__.py#FloatField) - Floating point number
- [`DecimalField`](./fields/__init__.py#DecimalField) - Fixed precision decimal

**Date and time fields:**

- [`DateField`](./fields/__init__.py#DateField) - Date (without time)
- [`DateTimeField`](./fields/__init__.py#DateTimeField) - Date with time
- [`TimeField`](./fields/__init__.py#TimeField) - Time (without date)
- [`DurationField`](./fields/__init__.py#DurationField) - Time duration (timedelta)
- [`TimeZoneField`](./fields/timezones.py#TimeZoneField) - Timezone (stored as string, accessed as ZoneInfo)

**Other fields:**

- [`BooleanField`](./fields/__init__.py#BooleanField) - True/False
- [`UUIDField`](./fields/__init__.py#UUIDField) - UUID (pass `generate=True` for a per-row `gen_random_uuid()` default)
- [`BinaryField`](./fields/__init__.py#BinaryField) - Raw binary data
- [`JSONField`](./fields/json.py#JSONField) - JSON data
- [`GenericIPAddressField`](./fields/__init__.py#GenericIPAddressField) - IPv4 or IPv6 address
- [`RandomStringField`](./fields/text.py#RandomStringField) - Per-row random hex string generated by Postgres (`length=`) — use for tokens, slugs, short IDs instead of a Python callable default. Slices `gen_random_uuid()` directly; values are uniform hex characters

**Encrypted fields:**

- [`EncryptedTextField`](./fields/encrypted.py#EncryptedTextField) - Text encrypted at rest
- [`EncryptedJSONField`](./fields/encrypted.py#EncryptedJSONField) - JSON encrypted at rest

See [Encrypted fields](#encrypted-fields) for details.

For relationship fields, see [Relationships](#relationships).

For nullable fields, use `| None` in the annotation and `default=None` to make
the field optional in the constructor:

```python
published_at: Field[datetime | None] = types.DateTimeField(
    allow_null=True, required=False, default=None
)
```

### Sharing fields across models

To share common fields across multiple models, use Python classes as mixins. A mixin that declares fields must inherit `postgres.ModelMixin`, and the final, registered model must inherit directly from `postgres.Model` (the mixins must not).

```python
from datetime import datetime

from plain import postgres
from plain.postgres import Field, ModelMixin, types


# Regular Python class for shared fields
class TimestampedMixin(ModelMixin):
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(update_now=True)
    source: Field[str] = types.TextField(max_length=50, required=False, default="")


# Models inherit from the mixin AND postgres.Model
@postgres.register_model
class User(TimestampedMixin, postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = PasswordField()
    is_admin: Field[bool] = types.BooleanField(default=False)


@postgres.register_model
class Note(TimestampedMixin, postgres.Model):
    content: Field[str] = types.TextField(max_length=1024)
    liked: Field[bool] = types.BooleanField(default=False)
```

`ModelMixin` is what puts the mixin's fields into each model's typed
constructor. The runtime collects fields off the whole MRO either way, but a
mixin inheriting nothing isn't visible to PEP 681, so the checker would reject
`Note(source="import")` on code that runs fine. `ModelMixin` carries no runtime
behavior — it's the same transform models get, and mixins are still declarations
you never instantiate directly.

That is also the one way to keep a **custom field type** required in the
constructor. A package that ships its own field type can declare the field on a
mixin carrying a transform that lists its constructor, and models mixing it in
get the field with its requiredness intact:

```python
from typing import dataclass_transform

from plain.postgres import Field
from plain.passwords.types import PasswordField


@dataclass_transform(kw_only_default=True, field_specifiers=(PasswordField,))
class _PasswordFieldSpec: ...


class PasswordMixin(_PasswordFieldSpec):
    password: Field[str] = PasswordField()
```

A model mixing in `PasswordMixin` now gets `password` as a required constructor
argument, so `User(email="a@b.com")` is a type error again. The specifier list
has to name every constructor the mixin's own body uses, core ones included.
Declared in the model's own body instead, `password` stays optional to the
checker — a model body is governed by the specifier list `plain.postgres`
declares, which a package outside it can't extend.

### Encrypted fields

Encrypted fields transparently encrypt values before writing to the database and decrypt on read. Use them for third-party credentials, API keys, OAuth tokens, and other secrets your application needs back in plaintext.

This is **not** for passwords or tokens you issue — those should be hashed (one-way). This is for secrets you receive from others and need to use later.

```python
from plain import postgres
from plain.postgres import EncryptedField, Field, types


@postgres.register_model
class Integration(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    api_key: EncryptedField[str] = types.EncryptedTextField(max_length=200)
    credentials: EncryptedField[dict | None] = types.EncryptedJSONField(
        required=False, allow_null=True, default=None
    )
```

Annotate encrypted fields `EncryptedField[T]`, not `Field[T]`. The annotation is
what the type checker reads, and `EncryptedField[T]` is the `Field[T]` subclass
that declares the blocked conditions — with a plain `Field[T]`,
`Integration.api_key.equals("x")` type-checks its way to a runtime `TypeError`
instead of being rejected at the call site. It types the constructor exactly as
`Field[T]` does.

Values are encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from `SECRET_KEY`. The `cryptography` package is required — install it with `pip install cryptography`.

**Available fields:**

- `EncryptedField[T]` — the annotation type; also the shared base the two fields below derive from.
- `EncryptedTextField` — encrypts text, stored as `text` in the database regardless of `max_length` (ciphertext is longer than plaintext). `max_length` is enforced on the plaintext value during validation.
- `EncryptedJSONField` — serializes to JSON, encrypts, and stores as `text`. Supports custom `encoder` and `decoder` parameters (same as `JSONField`).

**Limitations:**

- **No lookups** — encrypted values are non-deterministic (same plaintext produces different ciphertext each time), so filtering on encrypted fields doesn't work. Only `isnull` lookups are supported. Comparing against a value raises `TypeError` rather than silently matching nothing — both `filter(api_key="x")` and the typed [condition methods](#typed-conditions-with-where) (`equals`, `contains`, …), which are also rejected at the call site when the field is annotated `EncryptedField[T]`. `filter(api_key=None)` still rewrites to `IS NULL`.
- **`get_or_create()` must not look up an encrypted field.** `get_or_create(api_key="k")` raises, and the error says to move the value into `defaults=`. This is a deliberate break: it previously "worked" by creating a new row on every call, because the lookup could never match existing ciphertext. An encrypted value can be written, just not looked up:

    ```python
    Integration.query.get_or_create(name="acme", defaults={"api_key": "k"})
    ```

    The same applies to `upsert()`, and to an expression right-hand side like `filter(api_key=F("name"))` — the column is still ciphertext.

- **No indexes or constraints** — encrypted fields cannot be used in indexes or unique constraints. Preflight checks will catch this.
- **Only `default=""`** — on `EncryptedTextField` (paired with `required=False`), the empty string is stored as plaintext `''`, so it's the one value expressible as a column `DEFAULT` (declare it to add the field to a populated table). Any other default would need ciphertext, which is non-deterministic. `EncryptedJSONField` has no persistent default at all — even `{}` serializes to text that would need ciphertext — so pair `allow_null=True` with `default=None`, which stores nothing and just marks the field optional in the constructor.

**Key rotation:**

Encryption uses `SECRET_KEY`. When rotating keys, add the old key to `SECRET_KEY_FALLBACKS` — the field will decrypt with any fallback key and re-encrypt with the current key on save.

**Gradual migration:**

If you add encryption to an existing plaintext column, old unencrypted values are returned as-is on read (the field detects whether a value is encrypted by its `$fernet$` prefix). They'll be encrypted on the next save.

## Relationships

Use [`ForeignKeyField`](./fields/related.py#ForeignKeyField) for many-to-one and [`ManyToManyField`](./fields/related.py#ManyToManyField) for many-to-many:

```python
from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class Book(postgres.Model):
    title: Field[str] = types.TextField(max_length=200)
    author: Field[Author] = types.ForeignKeyField(Author, on_delete=postgres.CASCADE)
    tags = types.ManyToManyField("Tag")
```

### Referring to a model by name

`ForeignKeyField` also takes a `"package.Model"` string (or `"self"`) instead of
the class. That is a **runtime** device, for the cases where the class isn't
importable at the point of declaration: a circular reference between two models,
a self-reference, or a framework package pointing at the app's own `User`.

The annotation is unaffected — a string-referenced foreign key is annotated
`Field[Related]` exactly like a class-referenced one, and gets the same typed
surface: `Model.user.email.equals(...)` traversal, `Model.user.id.equals(...)`
conditions, and a typed `Model(user=...)` constructor. The string says nothing
to the checker, so the annotation is where `Related` comes from; import it under
`TYPE_CHECKING` when importing it for real would be the cycle you were avoiding:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from plain import postgres
from plain.postgres import Field, types

if TYPE_CHECKING:
    from app.users.models import User


@postgres.register_model
class PinnedNavItem(postgres.Model):
    # Cross-package: plain.admin can't import the app's User at runtime.
    user: Field[User] = types.ForeignKeyField("users.User", on_delete=postgres.CASCADE)


@postgres.register_model
class TreeNode(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    # Self-reference, nullable: `Field[T | None]` plus `default=None`.
    parent: Field[TreeNode | None] = types.ForeignKeyField(
        "self", on_delete=postgres.CASCADE, allow_null=True, default=None
    )
```

What does _not_ work is annotating the field with the related model itself
(`user: User = types.ForeignKeyField("users.User", ...)`). That names a model
instance rather than a field, so the checker never sees a descriptor: class
access is a `User` rather than `type[User]`, `Model.user.id` is an `int`, and
the condition methods are gone. `plain preflight`'s
`postgres.foreign_key_annotated_as_value` finds these: it reports a foreign key
whose annotation — on the model or on any of its base classes — names the
related model. It asks for positive evidence, so it stays quiet when it can't
establish that: an unannotated foreign key (no constructor argument at all), a
`ClassVar[...]` one, and any spelling whose meaning it can't read. Treat a clean
run as "nothing found", not "nothing to find".

### Foreign key access

Accessing a foreign key gives you the related object without a query — only its primary key is loaded up front:

```python
book = Book.query.get(id=1)
book.author  # no query — a partial Author instance
book.author.id  # no query — the foreign key value
book.author.name  # one query — loads the rest of the row
```

The first access to any non-key field loads the whole row in a single query. There is no separate `author_id` attribute — `book.author.id` is the foreign key value, and it is type-checked because `book.author` is an `Author`. In loops, use `join()` to load related rows up front and avoid a query per row.

A foreign key with no value raises `RelatedObjectDoesNotExist` on access. That attribute still lives on the descriptor at runtime, but class-level access is now typed as the related model (that is what makes `Book.author.name.equals(...)` work), so `Book.author.RelatedObjectDoesNotExist` is a type error. Catch it as `Author.DoesNotExist` — the exception subclasses both that and `AttributeError` — or as `AttributeError`.

The partial-instance shortcut is safe because Plain always creates a database foreign-key constraint, so the referenced row is guaranteed to exist.

### Constraints are checked immediately

Every constraint is checked at the write that violates it, never at commit — the same as Postgres's own default. Inserting a child row that points at a parent that doesn't exist yet fails at that `INSERT`, with a traceback pointing at the offending write, and deleting a parent with `RESTRICT` children fails at that `DELETE`. Create parents before children. A cycle of foreign keys needs a nullable back-reference: create both rows, then `update()` the back-reference. Two required foreign keys pointing at each other can never be inserted.

To swap two rows' values under a unique constraint (reordering by `position`, say), move one row to a temporary value first — a single `UPDATE` that swaps them fails, because Postgres checks uniqueness per row.

A migration can add a column, backfill it in `RunPython`, and drop or alter columns on the same table, all in one transaction.

### Reverse relationships

When you define a `ForeignKey` or `ManyToManyField`, Plain automatically creates a reverse accessor on the related model (like `author.book_set`). You can explicitly declare these reverse relationships using [`ReverseForeignKey`](./fields/reverse_descriptors.py#ReverseForeignKey) and [`ReverseManyToMany`](./fields/reverse_descriptors.py#ReverseManyToMany):

```python
from typing import ClassVar

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class Author(postgres.Model):
    name: Field[str] = types.TextField(max_length=200)
    # Explicit reverse accessor for all books by this author.
    # ClassVar keeps it out of the typed constructor (it's an accessor, not a field).
    books: ClassVar[types.ReverseForeignKey[Book]] = types.ReverseForeignKey(
        to="Book", field="author"
    )


@postgres.register_model
class Book(postgres.Model):
    title: Field[str] = types.TextField(max_length=200)
    author: Field[Author] = types.ForeignKeyField(Author, on_delete=postgres.CASCADE)


# Usage
author = Author.query.get(name="Jane Doe")
for book in author.books.all():
    print(book.title)

# Add a new book
author.books.create(title="New Book")
```

For many-to-many relationships:

```python
@postgres.register_model
class Feature(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    # Explicit reverse accessor for all cars with this feature
    cars: ClassVar[types.ReverseManyToMany[Car]] = types.ReverseManyToMany(
        to="Car", field="features"
    )


@postgres.register_model
class Car(postgres.Model):
    model: Field[str] = types.TextField(max_length=100)
    features = types.ManyToManyField(Feature)


# Usage
feature = Feature.query.get(name="Sunroof")
for car in feature.cars.all():
    print(car.model)
```

**Why use explicit reverse relations?**

- **Self-documenting**: The reverse accessor is visible in the model definition
- **Better IDE support**: Autocomplete works for reverse accessors
- **Type safety**: When combined with type annotations, type checkers understand the relationship
- **Control**: You choose the accessor name instead of relying on automatic `_set` naming

Reverse relations are optional — if you don't declare them, the automatic `{model}_set` accessor still works.

Annotate reverse relations with `ClassVar` — they're class-level accessors, not constructor fields, so `ClassVar` keeps them out of the typed `Model(...)` constructor (same as `query`). To get type checking for custom QuerySet methods, specify the QuerySet type as a second parameter:

```python
# Basic usage
books: ClassVar[types.ReverseForeignKey[Book]] = types.ReverseForeignKey(
    to="Book", field="author"
)

# With custom QuerySet for proper method recognition
books: ClassVar[types.ReverseForeignKey[Book, BookQuerySet]] = types.ReverseForeignKey(
    to="Book", field="author"
)

# Now type checkers recognize custom methods like .published()
author.books.query.published()
```

## Constraints

### Validation

`create()` and `update()` run `full_clean()` by default — field validators and the model's `clean()` method — raising `ValidationError` on violation. Pass `clean_and_validate=False` to skip it (e.g. for trusted bulk loads). Constraints are _not_ pre-checked here; the database enforces them (see below).

```python
@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    age: Field[int] = types.IntegerField()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="unique_email"),
        ],
    )

    def clean(self):
        if self.age < 18:
            raise ValidationError("User must be 18 or older")
```

Field-level validation happens automatically based on field types and constraints.

**The database is authoritative for constraints.** `create()`/`update()` don't pre-check your declared unique/check constraints — they attempt the write, and if Postgres rejects it, translate the `IntegrityError` into a `ValidationError` (routed to the field for single-column uniques, `NON_FIELD_ERRORS` otherwise). You get the same field-level error you'd expect, the write costs no per-constraint `SELECT`, and a raced concurrent insert can't slip through as a 500. A foreign key pointing at a row that doesn't exist maps the same way, as an error on that field. (`NOT NULL` and a hand-set primary-key collision have no declared constraint to map to and re-raise as the original `IntegrityError`. `create()` always inserts, so passing a stray `id` that already exists is rejected by Postgres as the original `IntegrityError`.)

Because the rejected write reaches the database, it aborts the surrounding transaction. If you catch the `ValidationError` and want to keep using the transaction, wrap the write in `transaction.atomic()` so it rolls back to a savepoint:

```python
try:
    with transaction.atomic():
        User.query.create(email=taken_email)
except ValidationError:
    ...  # report it — the transaction is still usable
```

Forms are the exception: a `ModelForm` pre-checks constraints explicitly (a `validate_constraints()` call in its `_post_clean`) so it can surface every violation at once, then writes via `form.create()`/`form.update()` with validation already done. A direct `create()`/`update()` reports the first violation Postgres hits.

This applies to instance writes only. Set-based writes — `QuerySet.update()` and `bulk_create()` — raise the raw `psycopg.IntegrityError`, since there's no instance to attribute the error to, and so does a `delete()` blocked by `RESTRICT` children. If you retry on a unique conflict, catch both:

```python
try:
    obj.create()
except psycopg.IntegrityError, ValidationError:
    ...  # lost a race — reload and retry, or report it
```

For a plain insert-or-update with no per-row logic there's no race to catch in the first place: `upsert(**values, unique_fields=[...])` for one row and `bulk_upsert(objs, update_fields=[...], unique_fields=[...])` for many are each a single atomic statement.

### Indexes and constraints

You can optimize queries and ensure data integrity with indexes and constraints. These are managed automatically by [convergence](#convergence) — just declare them on the model and run `postgres sync`.

```python
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    username: Field[str] = types.TextField(max_length=150)
    age: Field[int] = types.IntegerField()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(fields=["email"]),
            postgres.Index(fields=["-created_at"], name="user_created_idx"),
        ],
        constraints=[
            postgres.UniqueConstraint(fields=["email", "username"], name="unique_user"),
            postgres.CheckConstraint(check=postgres.Q(age__gte=0), name="age_positive"),
        ],
    )
```

Constraints are checked by `validate_constraints()` — run by a `ModelForm` (and any explicit `validate_constraints()` call), but **not** by `full_clean()` (which validates shape only) or a direct `create()`/`update()`, where the database enforces them instead (see [Validation](#validation)). Pass `violation_error` to customize the resulting `ValidationError`. It accepts anything `ValidationError(...)` accepts — a string, a `{field: message}` dict, or a fully-formed `ValidationError`:

```python
# Simple message — lands on NON_FIELD_ERRORS
postgres.CheckConstraint(
    check=postgres.Q(age__gte=0),
    name="age_positive",
    violation_error="Age must be zero or greater.",
)

# Dict form — routes to a specific field
postgres.CheckConstraint(
    check=postgres.Q(age__gte=0),
    name="age_positive",
    violation_error={"age": "Age must be zero or greater."},
)

# Full ValidationError — for code, params, multiple fields
postgres.CheckConstraint(
    check=postgres.Q(age__gte=0),
    name="age_positive",
    violation_error=ValidationError(
        {"age": "Age must be zero or greater."},
        code="age_negative",
    ),
)
```

A `code` becomes `ValidationError.code` — useful for test assertions, error tracking buckets, and code that branches on specific error types without string-matching.

`UniqueConstraint` accepts the same `violation_error`. With a single-field unique constraint, a string `violation_error="That email is taken."` auto-routes to that field; otherwise (multi-field, expressions, or a CheckConstraint) errors land on `NON_FIELD_ERRORS` unless you pass the dict form. See [BaseConstraint](./constraints.py#BaseConstraint) for the full signature.

### Storage parameters

Per-table Postgres [storage parameters](https://www.postgresql.org/docs/current/sql-createtable.html#SQL-CREATETABLE-STORAGE-PARAMETERS) (`pg_class.reloptions`) are declared on `model_options` and managed by [convergence](#convergence) — `postgres sync` issues the `ALTER TABLE … SET/RESET (...)` to make the live table match. They're not serialized into migrations.

```python
class CachedItem(postgres.Model):
    ...

    model_options = postgres.Options(
        storage_parameters={
            # Tighter autovacuum on a churn-heavy table
            "autovacuum_vacuum_scale_factor": 0.1,
            # TOAST has its own autovacuum schedule — prefix with `toast.`
            "toast.autovacuum_vacuum_scale_factor": 0.05,
        },
    )
```

Models are the source of truth: undeclared parameters set on the live table are reset on the next sync. Use this for autovacuum tuning, `fillfactor`, TOAST options, etc. — anything you'd otherwise apply by hand with `ALTER TABLE … SET (...)`.

### Schema design

#### Index fields used in filters and ordering

Add indexes for columns that appear in `.filter()`, `.order_by()`, or `.exclude()`.

```python
# Bad — full table scan on every filtered query
class Order(postgres.Model):
    status: Field[str] = types.TextField(max_length=20)
    created_at: Field[datetime] = types.DateTimeField()


# Good — indexed for common queries
class Order(postgres.Model):
    status: Field[str] = types.TextField(max_length=20)
    created_at: Field[datetime] = types.DateTimeField()

    model_options = postgres.Options(
        indexes=[postgres.Index(fields=["status", "-created_at"])],
    )
```

#### Use database constraints, not app-only validation

Enforce uniqueness and data integrity at the database level.

```python
# Bad — only validated in Python (racy: two requests can both pass the check)
def create(self):
    if MyModel.query.filter(email=self.email).exists():
        raise ValueError("duplicate")
    return super().create()


# Good — database-enforced
model_options = postgres.Options(
    constraints=[postgres.UniqueConstraint(fields=["email"])],
)
```

#### Choose `on_delete` deliberately

CASCADE for owned children, RESTRICT for referenced data, SET_NULL for optional references.

```python
# Bad — blindly using CASCADE everywhere
company: Field[Company] = types.ForeignKeyField(
    Company, on_delete=postgres.CASCADE
)  # deleting company deletes invoices!

# Good — block the delete while invoices reference the company
company: Field[Company] = types.ForeignKeyField(Company, on_delete=postgres.RESTRICT)
```

#### No `allow_null` on string fields

Use `default=""` instead of `allow_null=True` to avoid two representations of "empty."

```python
# Bad — NULL and "" both mean "empty"
nickname: Field[str] = types.TextField(max_length=50, allow_null=True)

# Good — single empty representation
nickname: Field[str] = types.TextField(max_length=50, default="")
```

## Forms

Models integrate with [plain.forms](../../../plain-forms/plain/forms/README.md):

```python
from plain import forms
from .models import User


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email", "is_admin")


# Usage
form = UserForm(request=request)
if form.is_valid():
    user = form.create()
```

## Architecture

```mermaid
graph TB
    subgraph "User API"
        Model["Model"]
        QS["QuerySet"]
        Expr["Expressions<br/><small>F() Q() Value()</small>"]
    end

    subgraph "Query Layer"
        Query["Query"]
        Where["WhereNode"]
        Join["Join"]
    end

    subgraph "Compilation"
        Compiler["SQLCompiler"]
    end

    subgraph "Database"
        Connection["DatabaseConnection"]
        DB[(Database)]
    end

    Model -- ".query" --> QS
    QS -- "owns" --> Query
    Expr -- "used by" --> Query
    Query -- "contains" --> Where
    Query -- "contains" --> Join
    Query -- "get_compiler()" --> Compiler
    Compiler -- "execute_sql()" --> Connection
    Connection -- "executes" --> DB
```

**Query execution flow:**

1. **Model.query** returns a [`QuerySet`](./query.py#QuerySet) bound to the model
2. **QuerySet** methods like `.filter()` modify the internal [`Query`](./sql/query.py#Query) object
3. When results are needed, **Query.get_compiler()** creates the appropriate [`SQLCompiler`](./sql/compiler.py#SQLCompiler)
4. **SQLCompiler.as_sql()** renders the Query to SQL
5. **SQLCompiler.execute_sql()** runs the SQL via [`DatabaseConnection`](./postgres/connection.py#DatabaseConnection) and returns results

**Key components:**

- [`Model`](./base.py#Model) - Defines fields, relationships, and provides the `query` attribute
- [`QuerySet`](./query.py#QuerySet) - Chainable API (`.filter()`, `.exclude()`, `.order_by()`) that builds a Query
- [`Query`](./sql/query.py#Query) - Internal representation of a query's logical structure (tables, joins, filters)
- [`SQLCompiler`](./sql/compiler.py#SQLCompiler) - Transforms a Query into executable SQL
- [`DatabaseConnection`](./postgres/connection.py#DatabaseConnection) - PostgreSQL connection and query execution

## Diagnostics

Run health checks against your database. `diagnose` is designed to produce
only actionable findings — every warning has a copy-paste fix or specific
resource to investigate, and noisy one-off signals (hit ratios, XID age) are
surfaced as informational context rather than as warnings.

```bash
uv run plain postgres diagnose
```

Output modes:

```bash
uv run plain postgres diagnose --json      # structured output for scripts/agents
uv run plain postgres diagnose --verbose   # expand to show every check, including passing
uv run plain postgres diagnose --all       # include findings on installed-package tables
```

### Guiding principle

`diagnose` emits a **warning** only if the remedy fits in the user's codebase
or is an app-level action they own. If the remedy is "run SQL against your
DB" or "configure your Postgres server," the check emits **operational
context** or an **informational number**, not a warning. This keeps the
warning surface high-trust — every warning has an edit-to-make — and prevents
`diagnose` from bleeding into DB-host concerns.

### Warning-tier checks

Things the user can fix by editing code + running `plain postgres sync`, or
app-level incidents they must act on.

**Structural — always-real; a fix is possible immediately.**

| Check                   | What it finds                                                                                       | Severity         |
| ----------------------- | --------------------------------------------------------------------------------------------------- | ---------------- |
| **Invalid indexes**     | Broken indexes from failed `CREATE INDEX CONCURRENTLY` — maintained on writes, never used for reads | Warning          |
| **Duplicate indexes**   | One index is a column-prefix of another on the same table                                           | Warning          |
| **Missing FK indexes**  | Foreign key columns without any index coverage                                                      | Warning          |
| **Sequence exhaustion** | Identity sequences approaching their type max                                                       | Warning/Critical |

**Cumulative — depends on stats since the last reset.**

| Check                        | What it finds                                                                                                        | Severity |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------- | -------- |
| **Unused indexes**           | Indexes with zero scans since stats reset (>1 MB). Excludes unique, constraint-backing, and sole-FK-coverage indexes | Warning  |
| **Missing index candidates** | Tables with seq-scan activity suggesting a missing index. Includes top contributing queries from pg_stat_statements  | Warning  |

**Snapshot — point-in-time incidents.**

| Check                        | What it finds                                                           | Severity         |
| ---------------------------- | ----------------------------------------------------------------------- | ---------------- |
| **Long-running connections** | Client backends idle-in-transaction or running a query past a threshold | Warning/Critical |
| **Blocking queries**         | Queries currently blocking other queries via held locks                 | Warning/Critical |

### Operational-context findings

These are facts about the database whose remedies live outside Plain today
(`ANALYZE`, `VACUUM`, `REINDEX`, autovacuum server tuning). They're surfaced
so agents and humans can interpret findings correctly, but the CLI renders
them as context rather than alarming warnings — the user can't express the
fix in their model code. (In JSON output each finding still carries
`status: "warning"`; the `tier: "operational"` field is what distinguishes
it.) Each finding still carries the exact SQL in its suggestion for anyone
who wants to act.

| Finding             | What it reports                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------ |
| **Stats freshness** | Tables whose planner statistics are missing (never analyzed) or stale                      |
| **Vacuum health**   | Tables with >10% dead tuples                                                               |
| **Table bloat**     | Tables with significant estimated wasted space (≥100 MB AND ≥25% bloat, ioguix estimator)  |
| **Index bloat**     | btree indexes with significant estimated wasted space (≥100 MB AND ≥30%, ioguix estimator) |

Now that per-table autovacuum / fillfactor knobs are expressible in
[storage parameters](#storage-parameters) on `model_options`, these
findings may graduate back to the warning tier in a future release — the
remedy is now in code.

### Informational context

Alongside checks, `diagnose` surfaces context an agent or human may want to read but that isn't actionable on its own:

- **Cache hit ratio**, **Index hit ratio** — buffer hit rates (volatile after restart; not a warning in themselves)
- **XID wraparound** — transaction ID age as a percent of the 2B limit. Autovacuum usually keeps this low; long-running transactions can block the freeze process even on managed Postgres
- **Connection saturation** — active/max connections at this moment
- **Stats reset** — when cumulative stats were last reset (affects the confidence of operational checks)
- **pg_stat_statements** — whether the extension is installed

### Cross-check caveats

Findings whose confidence depends on another check are tagged with a caveat. For example:

- `unused_indexes` on a table flagged by `stats_freshness` → caveat: "this table has never been analyzed — the planner may not yet use this index; re-check after running ANALYZE"
- `missing_index_candidates` on a never-analyzed table → caveat: "planner statistics are absent — running ANALYZE may change query plans and make this finding moot"

This prevents false confidence: dropping an "unused" index on a never-analyzed table is often the wrong move.

### Model-aware suggestions

Findings on app-owned tables include the Plain model class and its source file. Suggestions reference the exact edit point:

```
  app/processing/models.py :: ProcessingResult — Add an Index on ["is_processing"] to the model, then run plain postgres sync
```

This closes the loop from detection to fix — agents can draft the model edit without guessing.

### App vs package issues

Each finding is tagged with its **source**:

- **App** — your code, fully actionable
- **Package** — owned by an installed package (e.g., `plain-jobs`). These appear in the footer summary by default; use `--all` to see details
- **Unmanaged** — tables not managed by any Plain model. The suggestion includes exact SQL to run

### Production usage

Run diagnose against your **production database** to get meaningful stats. On Heroku:

```bash
heroku run -a your-app "plain postgres diagnose --json"
```

The `--json` flag must be quoted so Heroku passes it through to the command.

Cumulative-stat checks (`stats_freshness`, `vacuum_health`, `unused_indexes`, `missing_index_candidates`, `table_bloat`, `index_bloat`) need cumulative stat history after the last reset to be reliable. Check the `stats_reset` informational to see how much history you have. (Note: this list spans both the warning and operational tiers — the common thread is that all five depend on counters that `pg_stat_reset()` wipes.)

### Preflight checks

Two related checks run automatically during `uv run plain preflight` (and `uv run plain check`):

- **`postgres.missing_fk_indexes`** — warns about FK fields without index coverage in your model definitions
- **`postgres.duplicate_indexes`** — warns about prefix-redundant indexes in your model constraints

These are static, code-level checks that catch issues before you deploy. The `diagnose` command complements them with runtime stats from the actual database.

### What diagnose deliberately doesn't do

- **LLM-powered column recommendations for missing indexes** — `missing_index_candidates` shows the culprit queries and lets you decide. For precise column-level suggestions, use a platform tool (PlanetScale Insights, Dexter, pg_qualstats + hypopg).
- **Historical trending** — `diagnose` is stateless; it reports on the current state of cumulative stats. Continuous monitoring is out of scope.
- **Niche server checks** (WAL bloat, replication slot age, etc.) — better covered by your Postgres provider's monitoring or a dedicated tool; users on self-hosted setups that need them typically have their own tooling.

## Tracing

Every query runs inside an OpenTelemetry `CLIENT` span with standard `db.*` attributes, so queries show up as children of whatever request, job, or chore triggered them. You don't configure anything for this — it's on by default and only exports if your app exports traces (e.g. with [plain.connect](../../../plain-connect/plain/connect/README.md)).

If code runs a query with _no_ active span — a background thread, a polling loop — that query's span becomes its own single-span trace. For framework-internal housekeeping queries where that's pure noise, you can suppress query tracing entirely:

```python
from plain.postgres.otel import suppress_db_tracing

with suppress_db_tracing():
    MyModel.query.count()  # No span, no query metrics
```

This is meant for infrastructure code (pollers, metric gauge callbacks, test fixtures) — not for hiding application queries, which you almost always want visible in traces.

## Settings

The connection is configured with a single URL (`POSTGRES_URL`). `DATABASE_URL` is read as a platform-compat fallback. Set the URL to `none` to explicitly disable the database (e.g. during Docker image builds).

| Setting                                  | Type          | Default                 | Env var                                        |
| ---------------------------------------- | ------------- | ----------------------- | ---------------------------------------------- |
| `POSTGRES_URL`                           | `Secret[str]` | `$DATABASE_URL` or `""` | `PLAIN_POSTGRES_URL`                           |
| `POSTGRES_MANAGEMENT_URL`                | `Secret[str]` | `""`                    | `PLAIN_POSTGRES_MANAGEMENT_URL`                |
| `POSTGRES_POOL_MIN_SIZE`                 | `int`         | `4`                     | `PLAIN_POSTGRES_POOL_MIN_SIZE`                 |
| `POSTGRES_POOL_MAX_SIZE`                 | `int`         | `20`                    | `PLAIN_POSTGRES_POOL_MAX_SIZE`                 |
| `POSTGRES_POOL_MAX_LIFETIME`             | `float`       | `3600.0`                | `PLAIN_POSTGRES_POOL_MAX_LIFETIME`             |
| `POSTGRES_POOL_TIMEOUT`                  | `float`       | `30.0`                  | `PLAIN_POSTGRES_POOL_TIMEOUT`                  |
| `POSTGRES_MIGRATION_LOCK_TIMEOUT`        | `str`         | `"3s"`                  | `PLAIN_POSTGRES_MIGRATION_LOCK_TIMEOUT`        |
| `POSTGRES_MIGRATION_STATEMENT_TIMEOUT`   | `str`         | `"3s"`                  | `PLAIN_POSTGRES_MIGRATION_STATEMENT_TIMEOUT`   |
| `POSTGRES_CONVERGENCE_LOCK_TIMEOUT`      | `str`         | `"3s"`                  | `PLAIN_POSTGRES_CONVERGENCE_LOCK_TIMEOUT`      |
| `POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT` | `str`         | `"3s"`                  | `PLAIN_POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT` |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I add a field to an existing model?

Add the field to your model class, then run `plain migrations create` to create a migration.

If the field has no `default=` and isn't `allow_null=True`, the autodetector refuses to generate the migration, since there's no value to seed existing rows with — `required=False` alone is not enough (it only affects Python-side validation, not the column). You have two options:

1. Declare a `default=` on the field so the new column has a value for existing rows. For an optional string field the idiom is `required=False, default=""` (for `BinaryField`, `default=b""`).
2. Add the field with `allow_null=True`, scaffold a data migration with `plain migrations create --empty --name backfill_<field>` to populate existing rows, then remove `allow_null=True` from the field — convergence applies `NOT NULL` on the next `postgres sync`.

#### How do I make an existing column `NOT NULL`?

Edit the field to remove `allow_null=True`. `plain migrations create` won't detect a schema change — nullability is managed by convergence. Run `plain postgres sync`:

- If the column has no `NULL` rows, convergence applies the change with a non-blocking `CHECK NOT VALID` + `VALIDATE` + `SET NOT NULL` pattern.
- If `NULL` rows exist, convergence blocks and prints the table and column to backfill. Scaffold a data migration with `plain migrations create --empty --name backfill_<field>`, write the backfill, and run `postgres sync` again.

#### How do I create a unique constraint on multiple fields?

Use `UniqueConstraint` in your model's `model_options`:

```python
model_options = postgres.Options(
    constraints=[
        postgres.UniqueConstraint(
            fields=["email", "organization"], name="unique_email_per_org"
        ),
    ],
)
```

#### Can I use multiple databases?

Currently, Plain supports a single database connection per application. For applications requiring multiple databases, you can use raw SQL with separate connection management.

## Installation

Install the `plain.postgres` package from [PyPI](https://pypi.org/project/plain.postgres/). You must also pick a `psycopg` implementation — `plain.postgres` depends on `psycopg` but does not pick one for you, so installing `plain.postgres` alone will not be able to connect.

```bash
uv add plain.postgres psycopg[binary]  # Pre-built wheels, easiest for local development
# or
uv add plain.postgres psycopg[c]       # Compiled against your system's libpq, recommended for production
```

Then add to your `INSTALLED_PACKAGES` and register [`DatabaseConnectionMiddleware`](#middleware) so pooled connections are returned at the end of each request:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.postgres",
]

MIDDLEWARE = [
    "plain.postgres.DatabaseConnectionMiddleware",
    ...
]
```
