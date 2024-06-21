# bolt-auth

Add users to your app and define which views they can access.

To log a user in, you'll want to pair this package with:

- `bolt-passwords`
- `bolt-oauth`
- `bolt-passkeys` (TBD)
- `bolt-passlinks` (TBD)

## Installation

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "bolt.auth",
    "bolt.sessions",
    "bolt.passwords",
]

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.assets.whitenoise.middleware.WhiteNoiseMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",  # <--
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "bolt.auth.middleware.AuthenticationMiddleware",  # <--
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"
```

Create your own user model (`bolt create users`).

```python
# app/users/models.py
from bolt.db import models
from bolt.passwords.models import PasswordField


class User(models.Model):
    email = models.EmailField(unique=True)
    password = PasswordField()
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
```

Define your URL/view where users can log in.

```python
# app/urls.py
from bolt.auth.views import LoginView, LogoutView
from bolt.urls import include, path
from bolt.passwords.views import PasswordLoginView


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

Use the `AuthViewMixin` to restrict views to logged in users, staff users, or custom logic.

```python
from bolt.auth.views import AuthViewMixin
from bolt.exceptions import PermissionDenied
from bolt.views import View


class LoggedInView(AuthViewMixin, View):
    login_required = True


class StaffOnlyView(AuthViewMixin, View):
    login_required = True
    staff_required = True


class CustomPermissionView(AuthViewMixin, View):
    def check_auth(self):
        super().check_auth()
        if not self.request.user.is_special:
            raise PermissionDenied("You're not special!")
```
