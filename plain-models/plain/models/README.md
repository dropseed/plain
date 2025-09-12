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
plain models show-migrations
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

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["-created_at"], name="user_created_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["email", "username"], name="unique_user"),
            models.CheckConstraint(check=models.Q(age__gte=0), name="age_positive"),
        ]
```

## Custom QuerySets

With the Manager functionality now merged into QuerySet, you can customize [`QuerySet`](./query.py#QuerySet) classes to provide specialized query methods. There are several ways to use custom QuerySets:

### Setting a default QuerySet for a model

Use `Meta.queryset_class` to set a custom QuerySet that will be used by `Model.query`:

```python
class PublishedQuerySet(models.QuerySet):
    def published_only(self):
        return self.filter(status="published")

    def draft_only(self):
        return self.filter(status="draft")

@models.register_model
class Article(models.Model):
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)

    class Meta:
        queryset_class = PublishedQuerySet

# Usage - all methods available on Article.objects
all_articles = Article.query.all()
published_articles = Article.query.published_only()
draft_articles = Article.query.draft_only()
```

### Using custom QuerySets without formal attachment

You can also use custom QuerySets manually without setting them as the default:

```python
class SpecialQuerySet(models.QuerySet):
    def special_filter(self):
        return self.filter(special=True)

# Create and use the QuerySet manually
special_qs = SpecialQuerySet(model=Article)
special_articles = special_qs.special_filter()
```

### Using classmethods for convenience

For even cleaner API, add classmethods to your model:

```python
@models.register_model
class Article(models.Model):
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)

    @classmethod
    def published(cls):
        return PublishedQuerySet(model=cls).published_only()

    @classmethod
    def drafts(cls):
        return PublishedQuerySet(model=cls).draft_only()

# Usage
published_articles = Article.published()
draft_articles = Article.drafts()
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
