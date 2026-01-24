# plain.sessions

**Database-backed sessions for managing user state across requests.**

- [Overview](#overview)
- [Basic usage](#basic-usage)
- [Settings](#settings)
- [Session expiration](#session-expiration)
- [Session management](#session-management)
    - [Flushing sessions](#flushing-sessions)
    - [Cycling session keys](#cycling-session-keys)
    - [Checking if session is empty](#checking-if-session-is-empty)
- [Admin interface](#admin-interface)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Sessions allow you to store and retrieve arbitrary data on a per-visitor basis, using a session key stored in a cookie. You can use sessions as a dictionary-like object that automatically handles persistence to the database.

## Basic usage

In views that inherit from `SessionView`, you can use `self.session` like a standard Python dictionary:

```python
from plain.sessions.views import SessionView

class MyView(SessionView):
    def get(self):
        # Store values in the session
        self.session['username'] = 'jane'
        self.session['cart_items'] = [1, 2, 3]

        # Retrieve values from the session
        username = self.session.get('username')
        cart_items = self.session.get('cart_items', [])

        # Check if a key exists
        if 'username' in self.session:
            # User has a session
            pass

        # Delete values from the session
        del self.session['cart_items']
```

Outside of views, you can use `get_request_session()`:

```python
from plain.sessions import get_request_session

session = get_request_session(request)
session['key'] = 'value'
```

The session data is automatically saved when you set or delete values. Sessions are stored in the database using the [`Session`](./models.py#Session) model.

## Settings

| Setting                           | Default             | Env var |
| --------------------------------- | ------------------- | ------- |
| `SESSION_COOKIE_NAME`             | `"sessionid"`       | -       |
| `SESSION_COOKIE_AGE`              | `1209600` (2 weeks) | -       |
| `SESSION_COOKIE_DOMAIN`           | `None`              | -       |
| `SESSION_COOKIE_SECURE`           | `True`              | -       |
| `SESSION_COOKIE_PATH`             | `"/"`               | -       |
| `SESSION_COOKIE_HTTPONLY`         | `True`              | -       |
| `SESSION_COOKIE_SAMESITE`         | `"Lax"`             | -       |
| `SESSION_SAVE_EVERY_REQUEST`      | `False`             | -       |
| `SESSION_EXPIRE_AT_BROWSER_CLOSE` | `False`             | -       |

See [`default_settings.py`](./default_settings.py) for more details.

## Session expiration

Sessions expire `SESSION_COOKIE_AGE` seconds after they are **last saved** (not last accessed).

By default (`SESSION_SAVE_EVERY_REQUEST = False`), sessions are only saved when modified. For authenticated users, this means the expiration timer resets on login/logout but **not** when just browsing pages. Users will be logged out after `SESSION_COOKIE_AGE` even if actively using the site.

To extend sessions on every page access, set `SESSION_SAVE_EVERY_REQUEST = True`. This creates a sliding window where users stay logged in as long as they visit within `SESSION_COOKIE_AGE`, but increases database writes.

## Session management

The [`SessionStore`](./core.py#SessionStore) class provides additional methods for managing sessions.

### Flushing sessions

To completely remove the current session data and regenerate the session key:

```python
# In a view with SessionView
self.session.flush()

# Outside a view
from plain.sessions import get_request_session
session = get_request_session(request)
session.flush()
```

### Cycling session keys

To create a new session key while retaining the current session data (useful for security purposes):

```python
# In a view with SessionView
self.session.cycle_key()

# Outside a view
from plain.sessions import get_request_session
session = get_request_session(request)
session.cycle_key()
```

### Checking if session is empty

```python
# In a view with SessionView
if self.session.is_empty():
    # No session data exists
    pass

# Outside a view
from plain.sessions import get_request_session
session = get_request_session(request)
if session.is_empty():
    # No session data exists
    pass
```

## Admin interface

You can view and manage sessions in the admin panel under the "Sessions" section. The admin interface allows you to:

- Search sessions by session key
- View session creation and expiration times
- Delete expired or unwanted sessions

The [`SessionAdmin`](./admin.py#SessionAdmin) viewset provides the interface for managing sessions in the admin panel.

## FAQs

#### How do I clear expired sessions?

You can use the built-in [`ClearExpired`](./chores.py#ClearExpired) chore to delete expired sessions from the database:

```bash
plain chores run plain.sessions.chores.ClearExpired
```

You can schedule this chore to run periodically using `plain.worker` or your preferred task scheduler.

#### How do I access the underlying Session model instance?

You can access the database model instance through the `model_instance` property:

```python
from plain.sessions import get_request_session

session = get_request_session(request)
session_instance = session.model_instance  # Returns the Session model or None
```

#### Why is my session not being saved?

Sessions are only saved when modified (when you set or delete a value). If you need the session to be saved on every request, set `SESSION_SAVE_EVERY_REQUEST = True` in your settings.

## Installation

Install the `plain.sessions` package from [PyPI](https://pypi.org/project/plain.sessions/):

```bash
uv add plain.sessions
```

Add `plain.sessions` to your `INSTALLED_PACKAGES` and include the [`SessionMiddleware`](./middleware.py#SessionMiddleware) in your middleware:

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.sessions",
]

MIDDLEWARE = [
    # ...
    "plain.sessions.middleware.SessionMiddleware",
    # ...
]
```

Run migrations to create the session table:

```bash
plain migrate plain.sessions
```
