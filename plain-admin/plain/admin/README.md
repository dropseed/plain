# plain.admin

**Manage your app with a backend interface.**

- [Overview](#overview)
- [Admin viewsets](#admin-viewsets)
- [Admin cards](#admin-cards)
- [Admin forms](#admin-forms)
- [List displays](#list-displays)
- [Toolbar](#toolbar)
- [Impersonate](#impersonate)
- [Installation](#installation)

## Overview

The Plain Admin provides a combination of built-in views and the flexibility to create your own. You can use it to quickly get visibility into your app's data and to manage it.

![Plain Admin user example](https://assets.plainframework.com/docs/plain-pageviews-user.png)

The most common use of the admin is to manage your `plain.models`. To do this, create a [viewset](./views/viewsets.py#AdminViewset) with inner/nested views:

```python
# app/users/admin.py
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelUpdateView,
    AdminViewset,
    register_viewset,
)
from plain.models.forms import ModelForm

from .models import User


class UserForm(ModelForm):
    class Meta:
        model = User
        fields = ["email"]


@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        fields = [
            "id",
            "email",
            "created_at__date",
        ]
        queryset_order = ["-created_at"]
        search_fields = [
            "email",
        ]

    class DetailView(AdminModelDetailView):
        model = User

    class UpdateView(AdminModelUpdateView):
        template_name = "admin/users/user_form.html"
        model = User
        form_class = UserForm
```

## Admin viewsets

The [`AdminViewset`](./views/viewsets.py#AdminViewset) will automatically recognize inner views named `ListView`, `CreateView`, `DetailView`, `UpdateView`, and `DeleteView`. It will interlink these views automatically in the UI and form success URLs. You can define additional views too, but you will need to implement a couple methods to hook them up.

## Admin cards

TODO

## Admin forms

TODO

## List displays

On [`AdminListView`](./views/objects.py#AdminListView) and [`AdminModelListView`](./views/models.py#AdminModelListView), you can define different `displays` to build predefined views of your data. The display choices will be shown in the UI, and you can use the current `self.display` in your view logic.

```python
# app/users/admin.py
from plain.admin.views import AdminModelListView, register_viewset

from .models import User


@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        fields = [
            "id",
            "email",
            "created_at__date",
        ]
        displays = ["Users without email"]

        def get_objects(self):
            objects = super().get_objects()

            if self.display == "Users without email":
                objects = objects.filter(email="")

            return objects
```

## Toolbar

TODO

## Impersonate

TODO

## Installation

Install the `plain.admin` package from [PyPI](https://pypi.org/project/plain.admin/):

```bash
uv add plain.admin
```

The admin uses a combination of other Plain packages, most of which you will already have installed. Ultimately, your settings will look something like this:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.tailwind",
    "plain.auth",
    "plain.sessions",
    "plain.htmx",
    "plain.admin",
    "plain.elements",
    # other packages...
]

AUTH_USER_MODEL = "users.User"
AUTH_LOGIN_URL = "login"

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.admin.AdminMiddleware",
]
```

Your User model is expected to have an `is_admin` field (or attribute) for checking who has permission to access the admin.

```python
# app/users/models.py
from plain import models


@models.register_model
class User(models.Model):
    is_admin = models.BooleanField(default=False)
    # other fields...
```

To make the admin accessible, add the [`AdminRouter`](./urls.py#AdminRouter) to your root URLs.

```python
# app/urls.py
from plain.admin.urls import AdminRouter
from plain.urls import Router, include, path

from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        path("login/", views.LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        # other urls...
    ]
```
