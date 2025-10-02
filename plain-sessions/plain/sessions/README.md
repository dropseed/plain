# plain.sessions

**Database-backed sessions for managing user state across requests.**

- [Overview](#overview)
- [Basic usage](#basic-usage)
- [Session configuration](#session-configuration)
- [Session management](#session-management)
    - [Flushing sessions](#flushing-sessions)
    - [Cycling session keys](#cycling-session-keys)
    - [Checking if session is empty](#checking-if-session-is-empty)
- [Admin interface](#admin-interface)
- [Installation](#installation)

## Overview

The `plain.sessions` package provides database-backed session management for Plain applications. Sessions allow you to store and retrieve arbitrary data on a per-visitor basis, using a session key stored in a cookie.

Sessions are implemented as a dictionary-like object that automatically handles persistence to the database.

## Basic usage

In views that inherit from `SessionViewMixin`, you can use `self.session` like a standard Python dictionary:

```python
from plain.sessions.views import SessionViewMixin
from plain.views import View

class MyView(SessionViewMixin, View):
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

## Session configuration

Sessions can be configured through various settings:

```python
# Cookie name (default: "sessionid")
SESSION_COOKIE_NAME = "sessionid"

# Age of cookie in seconds (default: 2 weeks)
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7 * 2

# Domain for session cookie (None for standard domain cookie)
SESSION_COOKIE_DOMAIN = None

# Whether the session cookie should be secure (https:// only)
SESSION_COOKIE_SECURE = True

# The path of the session cookie
SESSION_COOKIE_PATH = "/"

# Whether to use the HttpOnly flag
SESSION_COOKIE_HTTPONLY = True

# Whether to set the flag restricting cookie leaks on cross-site requests
# Can be 'Lax', 'Strict', 'None', or False
SESSION_COOKIE_SAMESITE = "Lax"

# Whether to save the session data on every request
SESSION_SAVE_EVERY_REQUEST = False

# Whether a user's session cookie expires when the browser is closed
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
```

## Session management

The [`SessionStore`](./core.py#SessionStore) class provides additional methods for managing sessions:

### Flushing sessions

To completely remove the current session data and regenerate the session key:

```python
# In a view with SessionViewMixin
self.session.flush()

# Outside a view
from plain.sessions import get_request_session
session = get_request_session(request)
session.flush()
```

### Cycling session keys

To create a new session key while retaining the current session data (useful for security purposes):

```python
# In a view with SessionViewMixin
self.session.cycle_key()

# Outside a view
from plain.sessions import get_request_session
session = get_request_session(request)
session.cycle_key()
```

### Checking if session is empty

```python
# In a view with SessionViewMixin
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

The package includes an admin interface for viewing and managing sessions. Sessions can be viewed in the admin panel under the "Sessions" section, where you can:

- Search sessions by session key
- View session creation and expiration times
- Delete expired or unwanted sessions

The [`SessionAdmin`](./admin.py#SessionAdmin) viewset provides the interface for managing sessions in the admin panel.

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
