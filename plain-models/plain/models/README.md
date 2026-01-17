# plain.models

**Model your data and store it in a database.**

- [Overview](#overview)
- [Database connection](#database-connection)
- [Querying](#querying)
- [Migrations](#migrations)
- [Fields](#fields)
- [Reverse relationships](#reverse-relationships)
    - [Custom QuerySet typing](#custom-queryset-typing)
- [Typing](#typing)
    - [Typing QuerySets](#typing-querysets)
- [Validation](#validation)
- [Indexes and constraints](#indexes-and-constraints)
- [Custom QuerySets](#custom-querysets)
    - [Programmatic QuerySet usage](#programmatic-queryset-usage)
- [Forms](#forms)
- [Sharing fields across models](#sharing-fields-across-models)
- [Raw SQL](#raw-sql)
    - [Raw QuerySet](#raw-queryset)
    - [Database cursor](#database-cursor)
    - [SQL operations (UNION, etc.)](#sql-operations-union-etc)
- [Architecture](#architecture)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

```python
# app/users/models.py
from datetime import datetime

from plain import models
from plain.models import types
from plain.passwords.models import PasswordField


@models.register_model
class User(models.Model):
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

Or you can manually define the `DATABASE` setting:

```python
# app/settings.py
DATABASE = {
    "ENGINE": "plain.models.backends.postgresql",
    "NAME": "dbname",
    "USER": "user",
    "PASSWORD": "password",
    "HOST": "localhost",
    "PORT": "5432",
}
```

**PostgreSQL is the only supported database.**

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
from plain.models import Q
users = User.query.filter(
    Q(is_admin=True) | Q(email__endswith="@example.com")
)

# Ordering
users = User.query.order_by("-created_at")

# Limiting results
first_10_users = User.query.all()[:10]
```

For more advanced querying options, see the [`QuerySet`](./query.py#QuerySet) class.

## Migrations

Migrations track changes to your models and update the database schema accordingly:

```bash
# Create migrations for model changes
plain makemigrations

# Apply migrations to the database
plain migrate

# See migration status
plain migrations list
```

Migrations are Python files that describe database schema changes. They're stored in your app's `migrations/` directory.

## Fields

You can use many field types for different data:

```python
from plain import models

class Product(models.Model):
    # Text fields
    name = models.CharField(max_length=200)
    description = models.TextField()

    # Numeric fields
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField(default=0)

    # Boolean fields
    is_active = models.BooleanField(default=True)

    # Date and time fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Relationships
    category = models.ForeignKeyField("Category", on_delete=models.CASCADE)
    tags = models.ManyToManyField("Tag")
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

**Relationship fields:**

- [`ForeignKeyField`](./fields/related.py#ForeignKeyField) - Many-to-one relationship
- [`ManyToManyField`](./fields/related.py#ManyToManyField) - Many-to-many relationship

## Reverse relationships

When you define a `ForeignKey` or `ManyToManyField`, Plain automatically creates a reverse accessor on the related model (like `author.book_set`). You can explicitly declare these reverse relationships using [`ReverseForeignKey`](./fields/reverse_descriptors.py#ReverseForeignKey) and [`ReverseManyToMany`](./fields/reverse_descriptors.py#ReverseManyToMany):

```python
from plain import models

@models.register_model
class Author(models.Model):
    name = models.CharField(max_length=200)
    # Explicit reverse accessor for all books by this author
    books = models.ReverseForeignKey(to="Book", field="author")

@models.register_model
class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKeyField(Author, on_delete=models.CASCADE)

# Usage
author = Author.query.get(name="Jane Doe")
for book in author.books.all():
    print(book.title)

# Add a new book
author.books.create(title="New Book")
```

For many-to-many relationships:

```python
@models.register_model
class Feature(models.Model):
    name = models.CharField(max_length=100)
    # Explicit reverse accessor for all cars with this feature
    cars = models.ReverseManyToMany(to="Car", field="features")

@models.register_model
class Car(models.Model):
    model = models.CharField(max_length=100)
    features = models.ManyToManyField(Feature)

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

Reverse relations are optional - if you don't declare them, the automatic `{model}_set` accessor still works. You can also use both approaches in the same codebase.

### Custom QuerySet typing

To get type checking for custom QuerySet methods on reverse relations, specify the QuerySet type as a second parameter:

```python
# Basic usage
books: types.ReverseForeignKey[Book] = types.ReverseForeignKey(to="Book", field="author")

# With custom QuerySet for proper method recognition
books: types.ReverseForeignKey[Book, BookQuerySet] = types.ReverseForeignKey(to="Book", field="author")

# Now type checkers recognize custom methods like .published()
author.books.query.published()
```

## Typing

For better IDE support and type checking, use `plain.models.types` with type annotations:

```python
from plain import models
from plain.models import types

@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    username: str = types.CharField(max_length=150)
    is_admin: bool = types.BooleanField(default=False)
```

For nullable fields, add `| None` to the annotation:

```python
published_at: datetime | None = types.DateTimeField(allow_null=True, required=False)
```

Foreign keys are typed with the related model:

```python
author: Author = types.ForeignKeyField(Author, on_delete=models.CASCADE)
```

All field types from the [Fields](#fields) section are available through [`types`](./types.py). Typed and untyped fields can be mixed in the same model. The database behavior is identical - typed fields only add type checking.

Reverse relationships can also be typed - see the [Reverse relationships](#reverse-relationships) section for details.

### Typing QuerySets

For better type checking of query results, you can explicitly type the `query` attribute:

```python
from __future__ import annotations

from plain import models
from plain.models import types

@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    is_admin: bool = types.BooleanField(default=False)

    query: models.QuerySet[User] = models.QuerySet()
```

With this annotation, type checkers will know that `User.query.get()` returns a `User` instance and `User.query.filter()` returns `QuerySet[User]`. This is optional - the query attribute works without the annotation, but adding it improves IDE autocomplete and type checking.

## Validation

You can validate models before saving:

```python
class User(models.Model):
    email = models.EmailField(unique=True)
    age = models.IntegerField()

    def clean(self):
        if self.age < 18:
            raise ValidationError("User must be 18 or older")

    def save(self, *args, **kwargs):
        self.full_clean()  # Runs validation
        super().save(*args, **kwargs)
```

Field-level validation happens automatically based on field types and constraints.

## Indexes and constraints

You can optimize queries and ensure data integrity with indexes and constraints:

```python
class User(models.Model):
    email = models.EmailField()
    username = models.CharField(max_length=150)
    age = models.IntegerField()

    model_options = models.Options(
        indexes=[
            models.Index(fields=["email"]),
            models.Index(fields=["-created_at"], name="user_created_idx"),
        ],
        constraints=[
            models.UniqueConstraint(fields=["email", "username"], name="unique_user"),
            models.CheckConstraint(check=models.Q(age__gte=0), name="age_positive"),
        ],
    )
```

## Custom QuerySets

With the Manager functionality now merged into QuerySet, you can customize [`QuerySet`](./query.py#QuerySet) classes to provide specialized query methods.

Define a custom QuerySet and assign it to your model's `query` attribute:

```python
from typing import Self

class PublishedQuerySet(models.QuerySet["Article"]):
    def published_only(self) -> Self:
        return self.filter(status="published")

    def draft_only(self) -> Self:
        return self.filter(status="draft")

@models.register_model
class Article(models.Model):
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)

    query = PublishedQuerySet()

# Usage - all methods available on Article.query
all_articles = Article.query.all()
published_articles = Article.query.published_only()
draft_articles = Article.query.draft_only()
```

Custom methods can be chained with built-in QuerySet methods:

```python
# Chaining works naturally
recent_published = Article.query.published_only().order_by("-created_at")[:10]
```

### Programmatic QuerySet usage

For internal code that needs to create QuerySet instances programmatically, use `from_model()`:

```python
class SpecialQuerySet(models.QuerySet["Article"]):
    def special_filter(self) -> Self:
        return self.filter(special=True)

# Create and use the QuerySet programmatically
special_qs = SpecialQuerySet.from_model(Article)
special_articles = special_qs.special_filter()
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

## Sharing fields across models

To share common fields across multiple models, use Python classes as mixins. The final, registered model must inherit directly from `models.Model` and the mixins should not.

```python
from plain import models


# Regular Python class for shared fields
class TimestampedMixin:
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


# Models inherit from the mixin AND models.Model
@models.register_model
class User(TimestampedMixin, models.Model):
    email = models.EmailField()
    password = PasswordField()
    is_admin = models.BooleanField(default=False)


@models.register_model
class Note(TimestampedMixin, models.Model):
    content = models.TextField(max_length=1024)
    liked = models.BooleanField(default=False)
```

## Raw SQL

For complex queries that can't be expressed with the ORM, you can use raw SQL.

### Raw QuerySet

Use `Model.query.raw()` to execute raw SQL and get model instances back:

```python
# Execute raw SQL, returns User instances
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

### Database cursor

For queries that don't map to a model, use the database cursor directly:

```python
from plain.models import db_connection

with db_connection.cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = %s", [True])
    count = cursor.fetchone()[0]
```

### SQL operations (UNION, etc.)

For SQL set operations like UNION, INTERSECT, or EXCEPT, use raw SQL:

```python
# UNION - combine results from multiple queries
users = User.query.raw("""
    SELECT * FROM users WHERE is_admin = %s
    UNION
    SELECT * FROM users WHERE is_staff = %s
""", [True, True])

# INTERSECT - users matching both conditions
users = User.query.raw("""
    SELECT * FROM users WHERE is_admin = %s
    INTERSECT
    SELECT * FROM users WHERE is_staff = %s
""", [True, True])

# EXCEPT - admins who are not staff
users = User.query.raw("""
    SELECT * FROM users WHERE is_admin = %s
    EXCEPT
    SELECT * FROM users WHERE is_staff = %s
""", [True, True])
```

For simple cases, use Q objects instead of UNION:

```python
from plain.models import Q

# Equivalent to UNION (on same model)
users = User.query.filter(Q(is_admin=True) | Q(is_staff=True))
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
        Connection["DatabaseWrapper"]
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
5. **SQLCompiler.execute_sql()** runs the SQL via [`DatabaseWrapper`](./backends/wrapper.py#DatabaseWrapper) and returns results

**Key components:**

- [`Model`](./base.py#Model) - Defines fields, relationships, and provides the `query` attribute
- [`QuerySet`](./query.py#QuerySet) - Chainable API (`.filter()`, `.exclude()`, `.order_by()`) that builds a Query
- [`Query`](./sql/query.py#Query) - Internal representation of a query's logical structure (tables, joins, filters)
- [`SQLCompiler`](./sql/compiler.py#SQLCompiler) - Transforms a Query into executable SQL
- [`DatabaseWrapper`](./backends/wrapper.py#DatabaseWrapper) - PostgreSQL connection and query execution

## FAQs

#### How do I add a field to an existing model?

Add the field to your model class, then run `plain makemigrations` to create a migration. If the field is required (no default value and not nullable), you'll be prompted to provide a default value for existing rows.

#### What's the difference between `CharField` and `TextField`?

`CharField` requires a `max_length` and is typically used for short strings like names or emails. `TextField` has no length limit and is used for longer content like descriptions or body text.

#### How do I create a unique constraint on multiple fields?

Use `UniqueConstraint` in your model's `model_options`:

```python
model_options = models.Options(
    constraints=[
        models.UniqueConstraint(fields=["email", "organization"], name="unique_email_per_org"),
    ],
)
```

#### Can I use multiple databases?

Currently, Plain supports a single database connection per application. For applications requiring multiple databases, you can use raw SQL with separate connection management.

## Installation

Install the `plain.models` package from [PyPI](https://pypi.org/project/plain.models/):

```bash
uv add plain.models
```

Then add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.models",
]
```
