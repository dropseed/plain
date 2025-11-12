# plain.models

**Model your data and store it in a database.**

- [Overview](#overview)
- [Database connection](#database-connection)
- [Querying](#querying)
- [Migrations](#migrations)
- [Fields](#fields)
- [Validation](#validation)
- [Indexes and constraints](#indexes-and-constraints)
- [Custom QuerySets](#custom-querysets)
- [Forms](#forms)
- [Sharing fields across models](#sharing-fields-across-models)
- [Type annotations](#type-annotations)
- [Installation](#installation)

## Overview

```python
# app/users/models.py
from plain import models
from plain.passwords.models import PasswordField


@models.register_model
class User(models.Model):
    email = models.EmailField()
    password = PasswordField()
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
```

Every model automatically includes an `id` field which serves as the primary
key. The name `id` is reserved and can't be used for other fields.

Create, update, and delete instances of your models:

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

Multiple backends are supported, including Postgres, MySQL, and SQLite.

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

Plain provides many field types for different data:

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
    category = models.ForeignKey("Category", on_delete=models.CASCADE)
    tags = models.ManyToManyField("Tag")
```

Common field types include:

- [`CharField`](./fields/__init__.py#CharField)
- [`TextField`](./fields/__init__.py#TextField)
- [`IntegerField`](./fields/__init__.py#IntegerField)
- [`DecimalField`](./fields/__init__.py#DecimalField)
- [`BooleanField`](./fields/__init__.py#BooleanField)
- [`DateTimeField`](./fields/__init__.py#DateTimeField)
- [`EmailField`](./fields/__init__.py#EmailField)
- [`URLField`](./fields/__init__.py#URLField)
- [`UUIDField`](./fields/__init__.py#UUIDField)

## Validation

Models can be validated before saving:

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

Optimize queries and ensure data integrity with indexes and constraints:

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

Models integrate with Plain's form system:

```python
from plain import forms
from .models import User

class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "is_admin"]

# Usage
form = UserForm(data=request.data)
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

## Type annotations

You can write model fields with natural Python type annotations:

```python
class User(models.Model):
    email: str = models.EmailField()
    age: int = models.IntegerField()
    is_active: bool = models.BooleanField(default=True)
    created_at: datetime = models.DateTimeField(auto_now_add=True)
```

This provides IDE autocomplete and type checker support. Your IDE will know that `user.email` is a `str`, `user.age` is an `int`, etc.

Behind the scenes, Plain uses [type stubs](./fields/typing.pyi) to make field constructors appear to return their value types during type checking, while at runtime they return Field instances as expected. This dual behavior enables the natural syntax without affecting how Plain works internally.

Type annotations are optional but recommended for better IDE support.

### Optional fields with defaults

Fields with defaults (like `default=`, `auto_now_add=True`, or `required=False`) should include `| None` in their type annotation and use `= None` as a sentinel value. This tells type checkers that these fields are optional in `__init__`:

```python
from typing import Annotated
from datetime import datetime
from uuid import UUID

Field = Annotated

class Article(models.Model):
    # Required field - no | None, no = None
    title: Field[str, models.CharField(max_length=200)]

    # Fields with defaults - use | None and = None
    created_at: Field[datetime | None, models.DateTimeField(auto_now_add=True)] = None
    uuid: Field[UUID | None, models.UUIDField(default=uuid4)] = None
    status: Field[str | None, models.CharField(default="draft", max_length=20)] = None

    # Optional/nullable fields - use | None and = None
    published_at: Field[datetime | None, models.DateTimeField(required=False, allow_null=True)] = None
```

The `= None` is a sentinel value that signals to type checkers that the field has a default and doesn't need to be provided in `__init__`. At runtime, the field instance replaces this `None` value. The `| None` in the type reflects that the field value can be None (either from a default, auto-generation, or nullability).

**Note**: The `| None` is primarily a type-checker hint. It doesn't change runtime behavior - fields will still use their configured defaults and validation rules.

### Working with Field types directly

When you need to work with the actual Field types (not the value types), import `fields` directly from `plain.models`:

```python
from plain.models import fields

# Migrations - use fields.CharField() to get Field instances
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=fields.CharField(max_length=150),
        ),
    ]

# Custom field types - inherit from fields.CharField
class UpperCaseField(fields.CharField):
    def pre_save(self, model_instance, add):
        value = super().pre_save(model_instance, add)
        return value.upper() if value else value
```

This ensures you're working with Field instances rather than the type-checking stubs. This pattern is automatically used by Plain's migration generator.

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
