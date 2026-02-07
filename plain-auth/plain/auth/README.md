# plain.auth

**Add users to your app and decide what they can access.**

- [Overview](#overview)
- [Authentication setup](#authentication-setup)
    - [Settings configuration](#settings-configuration)
    - [Creating a user model](#creating-a-user-model)
    - [Login views](#login-views)
- [Checking if a user is logged in](#checking-if-a-user-is-logged-in)
- [Restricting views](#restricting-views)
- [Testing with authenticated users](#testing-with-authenticated-users)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain.auth` package handles user authentication and authorization for Plain applications. You can check if a user is logged in like this:

```python
from plain.auth import get_request_user

user = get_request_user(request)
if user:
    print(f"Hello, {user.email}!")
else:
    print("You are not logged in.")
```

You can restrict a view to logged-in users using [`AuthViewMixin`](./views.py#AuthViewMixin):

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

You can create your own user model using `plain create users` or manually:

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

To log users in, you need to pair this package with an authentication method:

- [plain.passwords](../../plain-passwords/plain/passwords/README.md) - Username/password authentication
- [plain.oauth](../../plain-oauth/plain/oauth/README.md) - OAuth provider authentication
- [plain.loginlink](../../plain-loginlink/plain/loginlink/README.md) - Magic link authentication

Here's an example with password authentication:

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

In templates, you can use the `get_current_user()` function:

```html
{% if get_current_user() %}
    <p>Hello, {{ get_current_user().email }}!</p>
{% else %}
    <p>You are not logged in.</p>
{% endif %}
```

In Python code, use [`get_request_user()`](./requests.py#get_request_user):

```python
from plain.auth import get_request_user

user = get_request_user(request)
if user:
    print(f"Hello, {user.email}!")
else:
    print("You are not logged in.")
```

## Restricting views

You can use [`AuthViewMixin`](./views.py#AuthViewMixin) to restrict views to logged-in users, admin users, or custom logic:

```python
from plain.auth.views import AuthViewMixin
from plain.http import ForbiddenError403
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
            raise ForbiddenError403("You're not special!")
```

The [`AuthViewMixin`](./views.py#AuthViewMixin) provides:

- `login_required` - Requires a logged-in user
- `admin_required` - Requires `user.is_admin` to be True
- `check_auth()` - Override for custom authorization logic

## Testing with authenticated users

When writing tests, you can use [`login_client()`](./test.py#login_client) to simulate an authenticated user:

```python
from plain.auth.test import login_client
from plain.test import Client

from app.users.models import User


def test_profile_view():
    user = User.objects.create(email="test@example.com")
    client = Client()
    login_client(client, user)

    response = client.get("/profile/")
    assert response.status_code == 200
```

You can also log out a test user with [`logout_client()`](./test.py#logout_client):

```python
from plain.auth.test import login_client, logout_client

# ... after logging in
logout_client(client)
```

## Settings

| Setting                        | Default              | Env var                              |
| ------------------------------ | -------------------- | ------------------------------------ |
| `AUTH_USER_MODEL`              | Required             | `PLAIN_AUTH_USER_MODEL`              |
| `AUTH_LOGIN_URL`               | Required             | `PLAIN_AUTH_LOGIN_URL`               |
| `AUTH_USER_SESSION_HASH_FIELD` | `"password"` or `""` | `PLAIN_AUTH_USER_SESSION_HASH_FIELD` |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I log in a user programmatically?

You can use the [`login()`](./sessions.py#login) function to log in a user:

```python
from plain.auth.sessions import login

login(request, user)
```

#### How do I log out a user programmatically?

You can use the [`logout()`](./sessions.py#logout) function:

```python
from plain.auth.sessions import logout

logout(request)
```

#### How do I invalidate sessions when a user changes their password?

By default, if you have [plain.passwords](../../plain-passwords/plain/passwords/README.md) installed, sessions are automatically invalidated when the `password` field changes. This is controlled by the `AUTH_USER_SESSION_HASH_FIELD` setting. You can change this to a different field name, or set it to an empty string to disable this feature.

#### How do I get the user model class?

You can use the [`get_user_model()`](./sessions.py#get_user_model) function:

```python
from plain.auth.sessions import get_user_model

User = get_user_model()
```

## Installation

Install the `plain.auth` package from [PyPI](https://pypi.org/project/plain.auth/):

```bash
uv add plain.auth
```
