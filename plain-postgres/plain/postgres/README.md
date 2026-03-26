# plain.postgres

**Model your data and store it in a database.**

- [Overview](#overview)
- [Database connection](#database-connection)
- [Querying](#querying)
- [Migrations](#migrations)
- [Fields](#fields)
- [Relationships](#relationships)
- [Constraints](#constraints)
- [Forms](#forms)
- [Architecture](#architecture)
- [Diagnostics](#diagnostics)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

```python
# app/users/models.py
from datetime import datetime

from plain import postgres
from plain.postgres import types
from plain.passwords.models import PasswordField


@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    password = PasswordField()
    is_admin: bool = types.BooleanField(default=False)
    created_at: datetime = types.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.email
```

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
user.save()

# Delete a user
user.delete()

# Query for users
admin_users = User.query.filter(is_admin=True)
```

## Database connection

To connect to a database, you can provide a `DATABASE_URL` environment variable:

```sh
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

Or you can set the individual `POSTGRES_*` settings (via `PLAIN_POSTGRES_*` environment variables or in `app/settings.py`):

```python
# app/settings.py
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DATABASE = "dbname"
POSTGRES_USER = "user"
POSTGRES_PASSWORD = "password"
```

If `DATABASE_URL` is set, it takes priority and the individual connection settings are parsed from it.

To explicitly disable the database (e.g. during Docker builds where no database is available), set `DATABASE_URL=none`.

**PostgreSQL is the only supported database.** You need to install a PostgreSQL driver separately — [psycopg](https://www.psycopg.org/) is recommended:

```bash
uv add psycopg[binary]  # Pre-built wheels, easiest for local development
# or
uv add psycopg[c]       # Compiled against your system's libpq, recommended for production
```

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
users = User.query.filter(
    Q(is_admin=True) | Q(email__endswith="@example.com")
)

# Ordering
users = User.query.order_by("-created_at")

# Limiting results
first_10_users = User.query.all()[:10]
```

For more advanced querying options, see the [`QuerySet`](./query.py#QuerySet) class.

### Custom QuerySets

You can customize [`QuerySet`](./query.py#QuerySet) classes to provide specialized query methods. Define a custom QuerySet and assign it to your model's `query` attribute:

```python
from typing import Self
from plain.postgres import types

class PublishedQuerySet(postgres.QuerySet["Article"]):
    def published_only(self) -> Self:
        return self.filter(status="published")

    def draft_only(self) -> Self:
        return self.filter(status="draft")

@postgres.register_model
class Article(postgres.Model):
    title: str = types.CharField(max_length=200)
    status: str = types.CharField(max_length=20)

    query = PublishedQuerySet()

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

For better type checking of query results, you can explicitly type the `query` attribute:

```python
from __future__ import annotations

from plain import postgres
from plain.postgres import types

@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    is_admin: bool = types.BooleanField(default=False)

    query: postgres.QuerySet[User] = postgres.QuerySet()
```

With this annotation, type checkers will know that `User.query.get()` returns a `User` instance and `User.query.filter()` returns `QuerySet[User]`. This is optional but improves IDE autocomplete and type checking.

### Raw SQL

For complex queries that can't be expressed with the ORM, you can use raw SQL.

Use `Model.query.raw()` to execute raw SQL and get model instances back:

```python
users = User.query.raw("""
    SELECT * FROM users
    WHERE created_at > %s
    ORDER BY created_at DESC
""", [some_date])

for user in users:
    print(user.email)  # Full model instance with all fields
```

Raw querysets support `prefetch_related()` for loading related objects:

```python
users = User.query.raw("SELECT * FROM users WHERE is_admin = %s", [True])
users = users.prefetch_related("posts")
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

#### Use `select_related` for ForeignKey access in loops

Accessing a FK in a loop without `select_related()` fires one query per row.

```python
# Bad — N+1 queries
for post in Post.query.all():
    print(post.author.name)

# Good — single JOIN
for post in Post.query.select_related("author").all():
    print(post.author.name)
```

#### Use `prefetch_related` for reverse/M2N access in loops

Reverse ForeignKey and ManyToMany relations need a separate prefetch query.

```python
# Bad — N+1 queries
for author in Author.query.all():
    print(author.posts.count())

# Good — one extra query
for author in Author.query.prefetch_related("posts").all():
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
    return {"posts": Post.query.select_related("author").prefetch_related("tags").all()}
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
if User.query.filter(is_active=True).count() > 0: ...

# Good
if User.query.filter(is_active=True).exists(): ...
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

Avoid calling `.save()` in a loop — each call is a separate query.

```python
# Bad — N INSERT statements
for name in names:
    Tag(name=name).save()

# Good — single INSERT
Tag.query.bulk_create([Tag(name=name) for name in names])
```

#### Use queryset `.update()` / `.delete()` for mass operations

```python
# Bad — N UPDATE statements
for user in User.query.filter(is_active=False):
    user.is_archived = True
    user.save()

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

## Transactions

By default, each query runs in its own implicit transaction and is committed immediately (autocommit mode). When you need multiple queries to succeed or fail together — like creating a user and their profile — wrap them in an explicit transaction.

### Atomic blocks

Wrap multiple queries in a transaction with `transaction.atomic()`:

```python
from plain.postgres import transaction

with transaction.atomic():
    user = User(email="test@example.com")
    user.save()
    Profile(user=user).save()
    # Both saves commit together, or both roll back on error
```

Nesting `atomic()` creates savepoints:

```python
with transaction.atomic():
    user.save()
    try:
        with transaction.atomic():
            risky_operation()  # If this fails...
    except SomeError:
        pass  # ...only the inner block rolls back
    safe_operation()  # This still runs in the outer transaction
```

### Read-only connections

Enforce read-only mode on the current database connection using `read_only()`. Any write (INSERT, UPDATE, DELETE, DDL) raises `psycopg.errors.ReadOnlySqlTransaction`:

```python
from plain.postgres.connections import read_only

with read_only():
    users = User.query.all()       # reads work
    User.query.create(name="x")   # raises psycopg.errors.ReadOnlySqlTransaction
```

This works with both autocommit queries and explicit `atomic()` blocks.

For sticky read-only mode (e.g., a shell session), use `set_read_only()` on the connection directly:

```python
from plain.postgres.db import get_connection

conn = get_connection()
conn.set_read_only(True)   # all subsequent queries are read-only
conn.set_read_only(False)  # back to normal
```

Read-only mode must be set outside a transaction — calling it inside `atomic()` raises `TransactionManagementError`.

## Migrations

Migrations track changes to your models and update the database schema accordingly. They are Python files stored in your app's `migrations/` directory.

### Creating migrations

```bash
plain makemigrations
```

Key flags:

- `--dry-run` — Show what migrations would be created (with operations and SQL) without writing files
- `--check` — Exit non-zero if migrations are needed (for CI)
- `--empty <package>` — Create an empty migration for custom data migrations
- `--name <name>` — Set the migration filename
- `-v 3` — Show full migration file contents

Only write migrations by hand if they are custom data migrations.

### Running migrations

```bash
plain migrate --backup
```

Key flags:

- `--backup` / `--no-backup` — Create a database backup before applying (default: on in DEBUG)
- `--plan` — Show what migrations would run without applying them
- `--check` — Exit non-zero if unapplied migrations exist (for CI)
- `--fake` — Mark migrations as applied without running them

### Viewing migration status

```bash
plain migrations list
```

`migrate` has no `--list` or `--status` flag. Use `plain migrations list`.

- `--format plan` — Show in dependency order instead of grouped by package

### Development workflow

During development, iterating on models often produces multiple small migrations (0002, 0003, 0004...). Clean these up before committing.

**Consolidating uncommitted migrations (delete-and-recreate):**

Use this when migrations exist only in your local dev environment and haven't been committed or deployed.

1. Delete the intermediate migration files (keep the initial 0001 and any previously committed migrations)
2. `plain migrations prune --yes` — removes stale DB records for the deleted files
3. `plain makemigrations` — creates a single fresh migration with all the changes
4. `plain migrate --fake` — marks the new migration as applied (the schema is already correct from the old migrations)

**Consolidating committed migrations (squash):**

Use this when migrations have already been committed or deployed to other environments.

`plain migrations squash <package> <migration>` creates a replacement migration with a `replaces` list. Keep the original files until all environments have migrated past the squash point, then delete them and run `migrations prune`.

**Which method to use:**

| Scenario                                  | Method                                                  |
| ----------------------------------------- | ------------------------------------------------------- |
| Migrations are local only (not committed) | Delete-and-recreate                                     |
| Migrations are committed but not deployed | Delete-and-recreate (if all developers reset) or squash |
| Migrations are deployed to production     | Squash or full reset                                    |

### Resetting migrations

Over time a package can accumulate dozens of migrations. Once **every environment** (dev, staging, production) has applied all of them, you can replace the entire history with a single fresh `0001_initial`.

**Prerequisites:**

- Every environment (dev, staging, production) has applied all existing migrations. If any environment is behind, the reset will break it.
- The first migration is named `0001_initial` (the default). If it has a different name, this workflow won't work cleanly.

**Steps:**

1. Run `plain migrations list` locally and verify everything is applied.
2. Delete every file in the package's `migrations/` directory except `__init__.py`.
3. Run `plain makemigrations` to generate a fresh `0001_initial`.
4. Run `plain migrations prune --yes` to remove stale DB records. The existing `0001_initial` record matches the new file, so the database is immediately up to date.
5. Verify with `plain postgres schema` (zero issues means the reset is clean) and `plain makemigrations --check` (no pending changes).
6. Commit and deploy. On every other environment, run `plain migrations prune --yes`. No actual SQL runs — it only cleans up migration history records. If `migrations prune` is already in your deploy steps, no changes are needed.

**Things to keep in mind:**

- If resetting multiple packages, process depended-on packages first — the new `0001_initial` may have cross-package FK dependencies.
- Data migrations (`RunPython`) in the deleted history are gone, which is fine since they've already run everywhere.
- If CI runs `makemigrations --check` or `migrate --check`, the reset PR must be merged and deployed before those checks pass in other branches.

### Other migration commands

- `plain migrations squash <package> <migration>` — Squash migrations into one
- `plain migrations prune` — Remove stale migration records

## Fields

You can use many field types for different data:

```python
from decimal import Decimal
from datetime import datetime

from plain import postgres
from plain.postgres import types

class Product(postgres.Model):
    # Text fields
    name: str = types.CharField(max_length=200)
    description: str = types.TextField()

    # Numeric fields
    price: Decimal = types.DecimalField(max_digits=10, decimal_places=2)
    quantity: int = types.IntegerField(default=0)

    # Boolean fields
    is_active: bool = types.BooleanField(default=True)

    # Date and time fields
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)
```

**Text fields:**

- [`CharField`](./fields/__init__.py#CharField) - String with max length
- [`TextField`](./fields/__init__.py#TextField) - Unlimited text
- [`EmailField`](./fields/__init__.py#EmailField) - Email address (validated)
- [`URLField`](./fields/__init__.py#URLField) - URL (validated)

**Numeric fields:**

- [`IntegerField`](./fields/__init__.py#IntegerField) - Integer
- [`BigIntegerField`](./fields/__init__.py#BigIntegerField) - Big (8 byte) integer
- [`SmallIntegerField`](./fields/__init__.py#SmallIntegerField) - Small integer
- [`PositiveIntegerField`](./fields/__init__.py#PositiveIntegerField) - Positive integer
- [`PositiveBigIntegerField`](./fields/__init__.py#PositiveBigIntegerField) - Positive big integer
- [`PositiveSmallIntegerField`](./fields/__init__.py#PositiveSmallIntegerField) - Positive small integer
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
- [`UUIDField`](./fields/__init__.py#UUIDField) - UUID
- [`BinaryField`](./fields/__init__.py#BinaryField) - Raw binary data
- [`JSONField`](./fields/json.py#JSONField) - JSON data
- [`GenericIPAddressField`](./fields/__init__.py#GenericIPAddressField) - IPv4 or IPv6 address

**Encrypted fields:**

- [`EncryptedTextField`](./fields/encrypted.py#EncryptedTextField) - Text encrypted at rest
- [`EncryptedJSONField`](./fields/encrypted.py#EncryptedJSONField) - JSON encrypted at rest

See [Encrypted fields](#encrypted-fields) for details.

For relationship fields, see [Relationships](#relationships).

For nullable fields, use `| None` in the annotation:

```python
published_at: datetime | None = types.DateTimeField(allow_null=True, required=False)
```

### Sharing fields across models

To share common fields across multiple models, use Python classes as mixins. The final, registered model must inherit directly from `postgres.Model` and the mixins should not.

```python
from datetime import datetime

from plain import postgres
from plain.postgres import types


# Regular Python class for shared fields
class TimestampedMixin:
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)


# Models inherit from the mixin AND postgres.Model
@postgres.register_model
class User(TimestampedMixin, postgres.Model):
    email: str = types.EmailField()
    password = PasswordField()
    is_admin: bool = types.BooleanField(default=False)


@postgres.register_model
class Note(TimestampedMixin, postgres.Model):
    content: str = types.TextField(max_length=1024)
    liked: bool = types.BooleanField(default=False)
```

### Encrypted fields

Encrypted fields transparently encrypt values before writing to the database and decrypt on read. Use them for third-party credentials, API keys, OAuth tokens, and other secrets your application needs back in plaintext.

This is **not** for passwords or tokens you issue — those should be hashed (one-way). This is for secrets you receive from others and need to use later.

```python
from plain import postgres
from plain.postgres import types

@postgres.register_model
class Integration(postgres.Model):
    name: str = types.CharField(max_length=100)
    api_key: str = types.EncryptedTextField(max_length=200)
    credentials: dict = types.EncryptedJSONField(required=False, allow_null=True)
```

Values are encrypted using Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from `SECRET_KEY`. The `cryptography` package is required — install it with `pip install cryptography`.

**Available fields:**

- `EncryptedTextField` — encrypts text, stored as `text` in the database regardless of `max_length` (ciphertext is longer than plaintext). `max_length` is enforced on the plaintext value during validation.
- `EncryptedJSONField` — serializes to JSON, encrypts, and stores as `text`. Supports custom `encoder` and `decoder` parameters (same as `JSONField`).

**Limitations:**

- **No lookups** — encrypted values are non-deterministic (same plaintext produces different ciphertext each time), so filtering on encrypted fields doesn't work. Only `isnull` lookups are supported.
- **No indexes or constraints** — encrypted fields cannot be used in indexes or unique constraints. Preflight checks will catch this.

**Key rotation:**

Encryption uses `SECRET_KEY`. When rotating keys, add the old key to `SECRET_KEY_FALLBACKS` — the field will decrypt with any fallback key and re-encrypt with the current key on save.

**Gradual migration:**

If you add encryption to an existing plaintext column, old unencrypted values are returned as-is on read (the field detects whether a value is encrypted by its `$fernet$` prefix). They'll be encrypted on the next save.

## Relationships

Use [`ForeignKeyField`](./fields/related.py#ForeignKeyField) for many-to-one and [`ManyToManyField`](./fields/related.py#ManyToManyField) for many-to-many:

```python
from plain import postgres
from plain.postgres import types

@postgres.register_model
class Book(postgres.Model):
    title: str = types.CharField(max_length=200)
    author: Author = types.ForeignKeyField("Author", on_delete=postgres.CASCADE)
    tags = types.ManyToManyField("Tag")
```

### Reverse relationships

When you define a `ForeignKey` or `ManyToManyField`, Plain automatically creates a reverse accessor on the related model (like `author.book_set`). You can explicitly declare these reverse relationships using [`ReverseForeignKey`](./fields/reverse_descriptors.py#ReverseForeignKey) and [`ReverseManyToMany`](./fields/reverse_descriptors.py#ReverseManyToMany):

```python
from plain import postgres
from plain.postgres import types

@postgres.register_model
class Author(postgres.Model):
    name: str = types.CharField(max_length=200)
    # Explicit reverse accessor for all books by this author
    books = types.ReverseForeignKey(to="Book", field="author")

@postgres.register_model
class Book(postgres.Model):
    title: str = types.CharField(max_length=200)
    author: Author = types.ForeignKeyField(Author, on_delete=postgres.CASCADE)

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
    name: str = types.CharField(max_length=100)
    # Explicit reverse accessor for all cars with this feature
    cars = types.ReverseManyToMany(to="Car", field="features")

@postgres.register_model
class Car(postgres.Model):
    model: str = types.CharField(max_length=100)
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

To get type checking for custom QuerySet methods on reverse relations, specify the QuerySet type as a second parameter:

```python
# Basic usage
books: types.ReverseForeignKey[Book] = types.ReverseForeignKey(to="Book", field="author")

# With custom QuerySet for proper method recognition
books: types.ReverseForeignKey[Book, BookQuerySet] = types.ReverseForeignKey(to="Book", field="author")

# Now type checkers recognize custom methods like .published()
author.books.query.published()
```

## Constraints

### Validation

You can validate models before saving:

```python
@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    age: int = types.IntegerField()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="unique_email"),
        ],
    )

    def clean(self):
        if self.age < 18:
            raise ValidationError("User must be 18 or older")

    def save(self, *args, **kwargs):
        self.full_clean()  # Runs validation
        super().save(*args, **kwargs)
```

Field-level validation happens automatically based on field types and constraints.

### Indexes and constraints

You can optimize queries and ensure data integrity with indexes and constraints:

```python
class User(postgres.Model):
    email: str = types.EmailField()
    username: str = types.CharField(max_length=150)
    age: int = types.IntegerField()

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

### Schema design

#### Index fields used in filters and ordering

Add indexes for columns that appear in `.filter()`, `.order_by()`, or `.exclude()`.

```python
# Bad — full table scan on every filtered query
class Order(postgres.Model):
    status: str = types.CharField(max_length=20)
    created_at: datetime = types.DateTimeField()

# Good — indexed for common queries
class Order(postgres.Model):
    status: str = types.CharField(max_length=20)
    created_at: datetime = types.DateTimeField()

    model_options = postgres.Options(
        indexes=[postgres.Index(fields=["status", "-created_at"])],
    )
```

#### Use database constraints, not app-only validation

Enforce uniqueness and data integrity at the database level.

```python
# Bad — only validated in Python
def save(self):
    if MyModel.query.filter(email=self.email).exists():
        raise ValueError("duplicate")

# Good — database-enforced
model_options = postgres.Options(
    constraints=[postgres.UniqueConstraint(fields=["email"])],
)
```

#### Choose `on_delete` deliberately

CASCADE for owned children, PROTECT for referenced data, SET_NULL for optional references.

```python
# Bad — blindly using CASCADE everywhere
company: Company = types.ForeignKeyField("Company", on_delete=postgres.CASCADE)  # deleting company deletes invoices!

# Good — protect referenced data
company: Company = types.ForeignKeyField("Company", on_delete=postgres.PROTECT)
```

#### No `allow_null` on string fields

Use `default=""` instead of `allow_null=True` to avoid two representations of "empty."

```python
# Bad — NULL and "" both mean "empty"
nickname: str = types.CharField(max_length=50, allow_null=True)

# Good — single empty representation
nickname: str = types.CharField(max_length=50, default="")
```

## Forms

Models integrate with [plain.forms](../../../plain-forms/plain/forms/README.md):

```python
from plain import forms
from .models import User

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "is_admin"]

# Usage
form = UserForm(request=request)
if form.is_valid():
    user = form.save()
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

You can run health checks against your database to find issues like missing indexes, redundant indexes, and configuration problems.

```bash
uv run plain postgres diagnose
```

Use `--json` for structured output (useful for scripting and AI agents):

```bash
uv run plain postgres diagnose --json
```

Use `--all` to include issues in installed packages (by default, only your app's issues are shown):

```bash
uv run plain postgres diagnose --all
```

### Checks

| Check                   | What it finds                                                                                                                                                  | Severity         |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| **Invalid indexes**     | Broken indexes from failed `CREATE INDEX CONCURRENTLY` — maintained on writes, never used for reads                                                            | Warning          |
| **Duplicate indexes**   | Indexes where one is a column-prefix of another on the same table (e.g., an auto FK index that's redundant with a composite index)                             | Warning          |
| **Unused indexes**      | Indexes with zero scans since stats reset (>1 MB). Excludes unique indexes, constraint-backing indexes, and indexes that are the sole coverage for a FK column | Warning          |
| **Missing FK indexes**  | Foreign key columns without any index coverage — parent DELETE/UPDATE operations will sequentially scan the child table                                        | Warning          |
| **Sequence exhaustion** | Identity sequences approaching their type max (>50% warning, >90% critical)                                                                                    | Warning/Critical |
| **XID wraparound**      | Transaction ID age approaching the 2 billion wraparound limit (>25% warning, >40% critical)                                                                    | Warning/Critical |
| **Cache hit ratio**     | Heap buffer hit ratio below 98.5% — indicates insufficient `shared_buffers` or RAM                                                                             | Warning          |
| **Index hit ratio**     | Index buffer hit ratio below 98.5%                                                                                                                             | Warning          |
| **Vacuum health**       | Tables with significant dead tuple accumulation (>10% of live rows) where autovacuum may be falling behind                                                     | Warning          |

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

### Preflight checks

Two related checks run automatically during `uv run plain preflight` (and `uv run plain check`):

- **`postgres.missing_fk_indexes`** — warns about FK fields without index coverage in your model definitions
- **`postgres.duplicate_indexes`** — warns about prefix-redundant indexes in your model constraints

These are static, code-level checks that catch issues before you deploy. The `diagnose` command complements them with runtime stats from the actual database.

## Settings

Connection settings are configured via `DATABASE_URL` or individual `POSTGRES_*` settings.

When `DATABASE_URL` is set, it is parsed into the individual connection settings automatically. When `DATABASE_URL` is not set, the connection settings are required individually.

Set `DATABASE_URL=none` to explicitly disable the database (e.g. during Docker image builds).

| Setting                       | Type          | Default | Env var                             |
| ----------------------------- | ------------- | ------- | ----------------------------------- |
| `POSTGRES_HOST`               | `str`         | —       | `PLAIN_POSTGRES_HOST`               |
| `POSTGRES_PORT`               | `int \| None` | `None`  | `PLAIN_POSTGRES_PORT`               |
| `POSTGRES_DATABASE`           | `str`         | —       | `PLAIN_POSTGRES_DATABASE`           |
| `POSTGRES_USER`               | `str`         | —       | `PLAIN_POSTGRES_USER`               |
| `POSTGRES_PASSWORD`           | `Secret[str]` | —       | `PLAIN_POSTGRES_PASSWORD`           |
| `POSTGRES_CONN_MAX_AGE`       | `int`         | `600`   | `PLAIN_POSTGRES_CONN_MAX_AGE`       |
| `POSTGRES_CONN_HEALTH_CHECKS` | `bool`        | `True`  | `PLAIN_POSTGRES_CONN_HEALTH_CHECKS` |
| `POSTGRES_OPTIONS`            | `dict`        | `{}`    | —                                   |
| `POSTGRES_TIME_ZONE`          | `str \| None` | `None`  | `PLAIN_POSTGRES_TIME_ZONE`          |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I add a field to an existing model?

Add the field to your model class, then run `plain makemigrations` to create a migration. If the field is required (no default value and not nullable), you'll be prompted to provide a default value for existing rows.

#### What's the difference between `CharField` and `TextField`?

`CharField` requires a `max_length` and is typically used for short strings like names or emails. `TextField` has no length limit and is used for longer content like descriptions or body text.

#### How do I create a unique constraint on multiple fields?

Use `UniqueConstraint` in your model's `model_options`:

```python
model_options = postgres.Options(
    constraints=[
        postgres.UniqueConstraint(fields=["email", "organization"], name="unique_email_per_org"),
    ],
)
```

#### Can I use multiple databases?

Currently, Plain supports a single database connection per application. For applications requiring multiple databases, you can use raw SQL with separate connection management.

## Installation

Install the `plain.postgres` package from [PyPI](https://pypi.org/project/plain.postgres/):

```bash
uv add plain.postgres psycopg[binary]
```

Then add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.postgres",
]
```
