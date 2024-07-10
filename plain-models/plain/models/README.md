# plain.models

Model your data and store it in a database.

```python
# app/users/models.py
from plain import models
from plain.passwords.models import PasswordField


class User(models.Model):
    email = models.EmailField(unique=True)
    password = PasswordField()
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
```

Create, update, and delete instances of your models:

```python
from .models import User


# Create a new user
user = User.objects.create(
    email="test@example.com",
    password="password",
)

# Update a user
user.email = "new@example.com"
user.save()

# Delete a user
user.delete()

# Query for users
staff_users = User.objects.filter(is_staff=True)
```

## Installation

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.models",
]
```

To connect to a database, you can provide a `DATABASE_URL` environment variable.

```sh
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

Or you can manually define the `DATABASES` setting.

```python
# app/settings.py
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.postgresql",
        "NAME": "dbname",
        "USER": "user",
        "PASSWORD": "password",
        "HOST": "localhost",
        "PORT": "5432",
    }
}
```

[Multiple backends are supported, including Postgres, MySQL, and SQLite.](./backends/README.md)

## Querying

## Migrations

[Migration docs](./migrations/README.md)

## Fields

[Field docs](./fields/README.md)

## Validation

## Indexes and constraints

## Managers

## Forms
