# Runtime

**Access and configure settings for your Plain application.**

- [Overview](#overview)
- [Environment variables](#environment-variables)
    - [.env files](#env-files)
    - [Custom prefixes](#custom-prefixes)
- [Package settings](#package-settings)
- [Custom app settings](#custom-app-settings)
- [Secret values](#secret-values)
- [Using Plain outside of an app](#using-plain-outside-of-an-app)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You configure Plain through settings, which are Python variables defined in your `app/settings.py` file.

```python
# app/settings.py
from plain.runtime import Secret

SECRET_KEY: Secret[str]

URLS_ROUTER = "app.urls.AppRouter"

TIME_ZONE = "America/Chicago"

INSTALLED_PACKAGES = [
    "plain.models",
    "plain.tailwind",
    "plain.auth",
    "plain.sessions",
    "plain.htmx",
    "plain.admin",
    # Local packages
    "app.users",
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.admin.AdminMiddleware",
]
```

You can access settings anywhere in your application via `plain.runtime.settings`.

```python
from plain.runtime import settings

print(settings.TIME_ZONE)
print(settings.DEBUG)
```

Plain's built-in settings are defined in [`global_settings.py`](./global_settings.py). Each installed package can also define its own settings in a `default_settings.py` file.

## Environment variables

Type-annotated settings can be loaded from environment variables using a `PLAIN_` prefix.

For example, if you define a setting with a type annotation:

```python
SECRET_KEY: str
```

You can set it via an environment variable:

```bash
PLAIN_SECRET_KEY=supersecret
```

For lists, dicts, and other complex types, use JSON-encoded values:

```python
ALLOWED_HOSTS: list[str]
```

```bash
PLAIN_ALLOWED_HOSTS='["example.com", "www.example.com"]'
```

Boolean settings accept `true`, `1`, `yes` (case-insensitive) as truthy values:

```bash
PLAIN_DEBUG=true
```

### .env files

Plain does not load `.env` files automatically. If you use [`plain.dev`](/plain-dev/README.md), it loads `.env` files for you during development. For production, you need to load them yourself or rely on your deployment platform to inject environment variables.

### Custom prefixes

You can configure additional environment variable prefixes using `ENV_SETTINGS_PREFIXES`:

```python
# app/settings.py
ENV_SETTINGS_PREFIXES = ["PLAIN_", "MYAPP_"]
```

Now both `PLAIN_DEBUG=true` and `MYAPP_DEBUG=true` would set the `DEBUG` setting. The first matching prefix wins if the same setting appears with multiple prefixes.

## Package settings

Installed packages can provide default settings via a `default_settings.py` file. It's best practice to prefix package settings with the package name to avoid conflicts.

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE = "user"
```

To make a setting required (no default value), define it with only a type annotation:

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE: str
```

Type annotations provide basic runtime validation. If a setting is defined as `str` but someone sets it to an `int`, Plain raises an error.

```python
# app/users/default_settings.py
USERS_DEFAULT_ROLE: str = "user"  # Optional with a default
```

## Custom app settings

You can create your own app-wide settings by prefixing them with `APP_`:

```python
# app/settings.py
import os

# A required env setting
APP_STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]

# An optional env setting
APP_GIT_SHA = os.environ.get("HEROKU_SLUG_COMMIT", "dev")[:7]

# A setting populated by Python code
with open("app/secret_key.txt") as f:
    APP_EXAMPLE_KEY = f.read().strip()
```

Settings without the `APP_` prefix that aren't recognized by Plain or installed packages will raise an error.

## Secret values

You can mark sensitive settings using the [`Secret`](./secret.py#Secret) type. Secret values are masked when displayed in logs or debugging output.

```python
from plain.runtime import Secret

SECRET_KEY: Secret[str]
DATABASE_PASSWORD: Secret[str]
```

At runtime, the value is still a plain string. The `Secret` type is purely a marker that tells Plain to mask the value when displaying settings.

## Using Plain outside of an app

If you need to use Plain in a standalone script, call `plain.runtime.setup()` first:

```python
import plain.runtime

plain.runtime.setup()

# Now you can use Plain normally
from plain.runtime import settings
print(settings.DEBUG)
```

The `setup()` function configures settings, logging, and populates the package registry. You can only call it once.

## FAQs

#### Where are the default settings defined?

Plain's core settings are in [`global_settings.py`](./global_settings.py). Each installed package can also have a `default_settings.py` file with package-specific defaults.

#### How do I see what settings are available?

Check [`global_settings.py`](./global_settings.py) for core settings. For package-specific settings, look at the `default_settings.py` file in each package.

#### What's the difference between required and optional settings?

A setting with only a type annotation (no value) is required:

```python
SECRET_KEY: str  # Required - must be set
```

A setting with a value is optional (has a default):

```python
DEBUG: bool = False  # Optional - defaults to False
```

#### Can I modify settings at runtime?

Yes, you can assign new values to settings after setup:

```python
from plain.runtime import settings

settings.DEBUG = True
```

#### What paths are available without setup?

`APP_PATH` and `PLAIN_TEMP_PATH` are available immediately without calling `setup()`:

```python
from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

print(APP_PATH)  # /path/to/project/app
print(PLAIN_TEMP_PATH)  # /path/to/project/.plain
```

## Installation

The runtime module is included with Plain by default. No additional installation is required.
