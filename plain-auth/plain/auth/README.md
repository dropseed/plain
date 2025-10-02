# plain.auth

**Add users to your app and decide what they can access.**

- [Overview](#overview)
- [Authentication setup](#authentication-setup)
    - [Settings configuration](#settings-configuration)
    - [Creating a user model](#creating-a-user-model)
    - [Login views](#login-views)
- [Checking if a user is logged in](#checking-if-a-user-is-logged-in)
- [Restricting views](#restricting-views)
- [Installation](#installation)

## Overview

The `plain.auth` package provides user authentication and authorization for Plain applications. Here's a basic example of checking if a user is logged in:

```python
# In a view
from plain.auth import get_request_user

user = get_request_user(request)
if user:
    print(f"Hello, {user.email}!")
else:
    print("You are not logged in.")
```

And restricting a view to logged-in users:

```python
from plain.auth.views import AuthViewMixin
from plain.views import View

class ProfileView(AuthViewMixin, View):
    login_required = True

    def get(self):
        return f"Welcome, {self.user.email}!"
```

## Authentication setup

### Settings configuration

Configure your authentication settings in `app/settings.py`:

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.auth",
    "plain.sessions",
    "plain.passwords",  # Or another auth method
]

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"
```

### Creating a user model

Create your own user model using `plain create users` or manually:

```python
# app/users/models.py
from plain import models
from plain.passwords.models import PasswordField


class User(models.Model):
    email = models.EmailField()
    password = PasswordField()
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
```

### Login views

To log users in, you'll need to pair this package with an authentication method:

- `plain-passwords` - Username/password authentication
- `plain-oauth` - OAuth provider authentication
- `plain-passkeys` (TBD) - WebAuthn/passkey authentication
- `plain-passlinks` (TBD) - Magic link authentication

Example with password authentication:

```python
# app/urls.py
from plain.auth.views import LogoutView
from plain.urls import path
from plain.passwords.views import PasswordLoginView


class LoginView(PasswordLoginView):
    template_name = "login.html"


urlpatterns = [
    path("logout/", LogoutView, name="logout"),
    path("login/", LoginView, name="login"),
]
```

## Checking if a user is logged in

In templates, use the `get_current_user()` function:

```html
{% if get_current_user() %}
    <p>Hello, {{ get_current_user().email }}!</p>
{% else %}
    <p>You are not logged in.</p>
{% endif %}
```

In Python code, use `get_request_user()`:

```python
from plain.auth import get_request_user

user = get_request_user(request)
if user:
    print(f"Hello, {user.email}!")
else:
    print("You are not logged in.")
```

## Restricting views

Use the [`AuthViewMixin`](./views.py#AuthViewMixin) to restrict views to logged-in users, admin users, or custom logic:

```python
from plain.auth.views import AuthViewMixin
from plain.exceptions import PermissionDenied
from plain.views import View


class LoggedInView(AuthViewMixin, View):
    login_required = True


class AdminOnlyView(AuthViewMixin, View):
    login_required = True
    admin_required = True


class CustomPermissionView(AuthViewMixin, View):
    def check_auth(self):
        super().check_auth()
        if not self.user.is_special:
            raise PermissionDenied("You're not special!")
```

The [`AuthViewMixin`](./views.py#AuthViewMixin) provides:

- `login_required` - Requires a logged-in user
- `admin_required` - Requires `user.is_admin` to be True
- `check_auth()` - Override for custom authorization logic

## Installation

Install the `plain.auth` package from [PyPI](https://pypi.org/project/plain.auth/):

```bash
uv add plain.auth
```
