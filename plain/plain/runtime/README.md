# Runtime

**Access app and package settings at runtime.**

Plain is configured by "settings", which are ultimately just Python variables. Most settings have default values which can be overidden either by your `app/settings.py` file or by environment variables.

```python
# app/settings.py
URLS_ROUTER = "app.urls.AppRouter"

TIME_ZONE = "America/Chicago"

INSTALLED_PACKAGES = [
    "plain.models",
    "plain.tailwind",
    "plain.auth",
    "plain.passwords",
    "plain.sessions",
    "plain.htmx",
    "plain.admin",
    "plain.elements",
    # Local packages
    "app.users",
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.admin.AdminMiddleware",
]
```

While working inside a Plain application or package, you can access settings at runtime via `plain.runtime.settings`.

```python
from plain.runtime import settings

print(settings.AN_EXAMPLE_SETTING)
```

The Plain core settings are defined in [`plain/runtime/global_settings.py`](global_settings.py) and you should look at that for reference. Each installed package can also define its own settings in a `default_settings.py` file.

## Environment variables

It's common in both development and production to use environment variables to manage settings. To handle this, any type-annotated setting can be loaded from the env with a `PLAIN_` prefix.

For example, to set the `SECRET_KEY` setting is defined with a type annotation.

```python
SECRET_KEY: str
```

And can be set by an environment variable.

```bash
PLAIN_SECRET_KEY=supersecret
```

For more complex types like lists or dictionaries, just use the `list` or `dict` type annotation and JSON-compatible types.

```python
LIST_EXAMPLE: list[str]
```

And set the environment variable with a JSON-encoded string.

```bash
PLAIN_LIST_EXAMPLE='["one", "two", "three"]'
```

Custom behavior can always be supported by checking the environment directly.

```python
# plain/models/default_settings.py
from os import environ

from . import database_url

# Make DATABASE a required setting
DATABASE: dict

# Automatically configure DATABASE if a DATABASE_URL was given in the environment
if "DATABASE_URL" in environ:
    DATABASE = database_url.parse_database_url(
        environ["DATABASE_URL"],
        # Enable persistent connections by default
        conn_max_age=int(environ.get("DATABASE_CONN_MAX_AGE", 600)),
        conn_health_checks=environ.get("DATABASE_CONN_HEALTH_CHECKS", "true").lower()
        in [
            "true",
            "1",
        ],
    )
```

### .env files

Plain itself does not load `.env` files automatically, except in development if you use [`plain.dev`](/plain-dev/README.md). If you use `.env` files in production then you will need to load them yourself.

## Package settings

An installed package can provide a `default_settings.py` file. It is strongly recommended to prefix any defined settings with the package name to avoid conflicts.

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE = "user"
```

The way you define these settings can impact the runtime behavior. For example, a required setting should be defined with a type annotation but no default value.

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE: str
```

Type annotations are only required for settings that don't provide a default value (to enable the environment variable loading). But generally type annotations are recommended as they also provide basic validation at runtime — if a setting is defined as a `str` but the user sets it to an `int`, an error will be raised.

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE: str = "user"
```

## Custom app-wide settings

At times it can be useful to create your own settings that are used across your application. When you define these in `app/settings.py`, you simply prefix them with `APP_` which marks them as a custom setting.

```python
# app/settings.py
# A required env setting
APP_STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]

# An optional env setting
APP_GIT_SHA = os.environ.get("HEROKU_SLUG_COMMIT", "dev")[:7]

# A setting populated by Python code
with open("app/secret_key.txt") as f:
    APP_EXAMPLE_KEY = f.read().strip()
```

## Using Plain in other environments

There may be some situations where you want to manually invoke Plain, like in a Python script. To get everything set up, you can call the `plain.runtime.setup()` function.

```python
import plain.runtime

plain.runtime.setup()
```
