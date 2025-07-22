# plain.models

**Model your data and store it in a database.**

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
admin_users = User.objects.filter(is_admin=True)
```

## Installation

Install `plain.models` from PyPI, then add it to your `INSTALLED_PACKAGES`.

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

Or you can manually define the `DATABASE` setting.

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

TODO

## Migrations

TODO

## Fields

TODO

## Validation

TODO

## Indexes and constraints

TODO

## Managers

TODO

## Forms

TODO
