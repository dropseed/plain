# plain.auth

Add users to your app and define which views they can access.

To log a user in, you'll want to pair this package with:

- `plain-passwords`
- `plain-oauth`
- `plain-passkeys` (TBD)
- `plain-passlinks` (TBD)

## Installation

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.auth",
    "plain.sessions",
    "plain.passwords",
]

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"
```

Create your own user model (`plain create users`).

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

Define your URL/view where users can log in.

```python
# app/urls.py
from plain.auth.views import LoginView, LogoutView
from plain.urls import include, path
from plain.passwords.views import PasswordLoginView


class LoginView(PasswordLoginView):
    template_name = "login.html"


urlpatterns = [
    path("logout/", LogoutView, name="logout"),
    path("login/", LoginView, name="login"),
]
```

## Checking if a user is logged in

A `request.user` will either be `None` or point to an instance of a your `AUTH_USER_MODEL`.

So in templates you can do:

```html
{% if request.user %}
    <p>Hello, {{ request.user.email }}!</p>
{% else %}
    <p>You are not logged in.</p>
{% endif %}
```

Or in Python:

```python
if request.user:
    print(f"Hello, {request.user.email}!")
else:
    print("You are not logged in.")
```

## Restricting views

Use the `AuthViewMixin` to restrict views to logged in users, admin users, or custom logic.

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
        if not self.request.user.is_special:
            raise PermissionDenied("You're not special!")
```
