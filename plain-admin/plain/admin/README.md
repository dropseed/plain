# plain.admin

**Manage your app with a backend interface.**

- [Overview](#overview)
- [Admin viewsets](#admin-viewsets)
    - [Model views](#model-views)
    - [Object views](#object-views)
    - [Navigation](#navigation)
- [Links](#links)
- [Admin cards](#admin-cards)
    - [Basic cards](#basic-cards)
    - [Trend cards](#trend-cards)
    - [Table cards](#table-cards)
- [Admin forms](#admin-forms)
- [List filters](#list-filters)
- [Actions](#actions)
- [Toolbar](#toolbar)
- [Impersonate](#impersonate)
- [Customization](#customization)
    - [Header branding](#header-branding)
    - [User avatar](#user-avatar)
    - [User menu items](#user-menu-items)
- [Access control](#access-control)
    - [Per-view restriction](#per-view-restriction)
    - [Global restriction](#global-restriction)
- [FAQs](#faqs)
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

The [`AdminViewset`](./views/viewsets.py#AdminViewset) automatically recognizes inner views named `ListView`, `CreateView`, `DetailView`, `UpdateView`, and `DeleteView`. It interlinks these views automatically in the UI and sets up form success URLs. You can define additional views too, but you will need to implement a couple methods to hook them up.

### Model views

For working with database models, use the model-specific view classes. These handle common patterns like automatic URL paths, queryset ordering, and search.

- [`AdminModelListView`](./views/models.py#AdminModelListView) - Lists model instances with pagination, search, and sorting
- [`AdminModelDetailView`](./views/models.py#AdminModelDetailView) - Shows a single model instance with all its fields
- [`AdminModelCreateView`](./views/models.py#AdminModelCreateView) - Creates new model instances using a form
- [`AdminModelUpdateView`](./views/models.py#AdminModelUpdateView) - Updates existing model instances
- [`AdminModelDeleteView`](./views/models.py#AdminModelDeleteView) - Deletes model instances with confirmation

```python
@register_viewset
class ProductAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Product
        fields = ["id", "name", "price", "created_at"]
        queryset_order = ["-created_at"]
        search_fields = ["name", "description"]

    class DetailView(AdminModelDetailView):
        model = Product
        fields = ["id", "name", "description", "price", "created_at", "updated_at"]

    class CreateView(AdminModelCreateView):
        model = Product
        form_class = ProductForm

    class UpdateView(AdminModelUpdateView):
        model = Product
        form_class = ProductForm

    class DeleteView(AdminModelDeleteView):
        model = Product
```

The `fields` attribute on list and detail views supports the `__` syntax for accessing related objects and calling methods. For example, `"created_at__date"` will call the `date()` method on the datetime field.

### Object views

For working with non-model data (API responses, files, etc.), use the base object views. These require you to implement `get_initial_objects()` or `get_object()` methods.

- [`AdminListView`](./views/objects.py#AdminListView) - Base list view for any iterable
- [`AdminDetailView`](./views/objects.py#AdminDetailView) - Base detail view for any object
- [`AdminCreateView`](./views/objects.py#AdminCreateView) - Base create view
- [`AdminUpdateView`](./views/objects.py#AdminUpdateView) - Base update view
- [`AdminDeleteView`](./views/objects.py#AdminDeleteView) - Base delete view

```python
from plain.admin.views import AdminListView, AdminViewset, register_viewset


@register_viewset
class ExternalAPIAdmin(AdminViewset):
    class ListView(AdminListView):
        title = "External Items"
        nav_section = "Integrations"
        path = "external-items/"
        fields = ["id", "name", "status"]

        def get_initial_objects(self):
            # Fetch from an external API, file, or any data source
            return external_api.get_items()
```

### Navigation

Views appear in the admin sidebar based on their `nav_section` and `nav_title` attributes. Set `nav_section` to group related views together.

```python
class ListView(AdminModelListView):
    model = Order
    nav_section = "Sales"  # Groups this view under "Sales" in the sidebar
    nav_title = "Orders"   # Display name (defaults to model name)
    nav_icon = "shopping-cart"  # Icon for the section
```

Icons come from [Bootstrap Icons](https://icons.getbootstrap.com/). To search available icon names:

```bash
uv run plain admin icons         # List all ~2,078 icons
uv run plain admin icons cart    # Search by keyword
```

Setting `nav_section = None` hides a view from the navigation entirely.

## Links

Admin views can display action links in their title bar. There are two types: **links** appear as visible buttons, while **extra links** are tucked into a three-dots overflow dropdown.

On mobile, both link types are combined into a single dropdown menu.

```python
from plain.urls import reverse


@register_viewset
class OrderAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Order

        def get_extra_links(self):
            extra_links = super().get_extra_links()
            extra_links["Import"] = reverse("orders:import")
            return extra_links

    class DetailView(AdminModelDetailView):
        model = Order

        def get_extra_links(self):
            extra_links = super().get_extra_links()
            extra_links["Export PDF"] = reverse("orders:export", pk=self.object.pk)
            return extra_links
```

Viewsets already populate `links` automatically — list views get a "New" link if a `CreateView` exists, and detail views get "Edit" and "Delete" links for their respective views. Use `get_extra_links()` for additional actions that don't need primary button visibility.

## Admin cards

Cards display summary information on admin pages. You can add them to any view by setting the `cards` attribute.

### Basic cards

The base [`Card`](./cards/base.py#Card) class displays a simple card with a title, optional description, metric, text, and link.

```python
from plain.admin.cards import Card
from plain.admin.views import AdminView, register_view


class UsersCard(Card):
    title = "Total Users"
    size = Card.Sizes.SMALL

    def get_metric(self):
        from app.users.models import User
        return User.query.count()

    def get_link(self):
        return "/admin/p/user/"


@register_view
class DashboardView(AdminView):
    title = "Dashboard"
    path = "dashboard/"
    nav_section = ""
    cards = [UsersCard]
```

Card sizes control how much horizontal space they occupy in a four-column grid:

- `Card.Sizes.SMALL` - 1 column (default)
- `Card.Sizes.MEDIUM` - 2 columns
- `Card.Sizes.LARGE` - 3 columns
- `Card.Sizes.FULL` - 4 columns (full width)

### Trend cards

The [`TrendCard`](./cards/charts.py#TrendCard) displays a bar chart showing data over time. It works with models that have a datetime field.

```python
from plain.admin.cards import TrendCard
from plain.admin.dates import DatetimeRangeAliases


class SignupsTrendCard(TrendCard):
    title = "User Signups"
    size = TrendCard.Sizes.MEDIUM
    model = User
    datetime_field = "created_at"
    default_preset = DatetimeRangeAliases.SINCE_30_DAYS_AGO
```

Trend cards include built-in date range presets like "Today", "This Week", "Last 30 Days", etc. Users can switch between presets in the UI.

For custom chart data, override the `get_trend_data()` method to return a dict mapping date strings to counts.

### Table cards

The [`TableCard`](./cards/tables.py#TableCard) displays tabular data with headers, rows, and optional footers.

```python
from plain.admin.cards import TableCard


class RecentOrdersCard(TableCard):
    title = "Recent Orders"
    size = TableCard.Sizes.FULL  # Tables typically use full width

    def get_headers(self):
        return ["Order ID", "Customer", "Total", "Status"]

    def get_rows(self):
        orders = Order.query.order_by("-created_at")[:5]
        return [
            [order.id, order.customer.name, order.total, order.status]
            for order in orders
        ]
```

## Admin forms

Admin forms work with standard [plain.forms](/plain/plain/forms/README.md). For model-based forms, use [`ModelForm`](/plain-models/plain/models/forms.py#ModelForm).

```python
from plain.models.forms import ModelForm
from plain.admin.views import AdminModelUpdateView


class UserForm(ModelForm):
    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "is_active"]


class UpdateView(AdminModelUpdateView):
    model = User
    form_class = UserForm
    template_name = "admin/users/user_form.html"  # Optional custom template
```

The form template should extend the admin base and use the form rendering helpers.

```html
{% extends "admin/base.html" %}

{% block content %}
<form method="post">
    {{ csrf_input }}
    {{ form.as_p }}
    <button type="submit">Save</button>
</form>
{% endblock %}
```

## List filters

On [`AdminListView`](./views/objects.py#AdminListView) and [`AdminModelListView`](./views/models.py#AdminModelListView), you can define different `filters` to build predefined views of your data. The filter choices will be shown in the UI, and you can use the current `self.filter` in your view logic.

```python
@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        fields = [
            "id",
            "email",
            "created_at__date",
        ]
        filters = ["Active users", "Inactive users"]

        def filter_queryset(self, queryset):
            if self.filter == "Active users":
                return queryset.filter(is_active=True)
            elif self.filter == "Inactive users":
                return queryset.filter(is_active=False)
            return queryset
```

## Actions

List views support bulk actions on selected items. Define actions as a list of action names, then implement `perform_action()` to handle them.

```python
class ListView(AdminModelListView):
    model = User
    fields = ["id", "email", "is_active"]
    actions = ["Activate", "Deactivate", "Delete selected"]

    def perform_action(self, action, target_ids):
        users = User.query.filter(id__in=target_ids)

        if action == "Activate":
            users.update(is_active=True)
        elif action == "Deactivate":
            users.update(is_active=False)
        elif action == "Delete selected":
            users.delete()

        # Return None to redirect back to the list, or return a Response
        return None
```

The `target_ids` parameter contains the IDs of selected items. Users can select individual items or use "Select all" to target the entire filtered queryset.

## Toolbar

The admin includes a toolbar component that appears on your frontend when an admin user is logged in. This toolbar provides quick access to the admin and shows a link to edit the current object if one is detected.

The toolbar is registered automatically when you include `plain.admin` in your installed packages. It uses [`plain.toolbar`](/plain-toolbar/plain/toolbar/README.md) to render on your pages.

To enable the toolbar on your frontend, add the toolbar middleware and include the toolbar template tag in your base template:

```python
# app/settings.py
MIDDLEWARE = [
    # ...other middleware
    "plain.toolbar.ToolbarMiddleware",
]
```

```html
<!-- In your base template -->
{% load toolbar %}
{% toolbar %}
```

When viewing a page that has an `object` in the template context, the toolbar will show a link to that object's admin detail page (if one exists).

## Impersonate

The impersonate feature lets admin users log in as another user to debug issues or provide support. This is useful for seeing exactly what a user sees without needing their credentials.

To start impersonating, visit a user's detail page in the admin and click the "Impersonate" link. The admin toolbar will show who you're impersonating and provide a link to stop.

By default, users with `is_admin=True` can impersonate other users. Admin users cannot be impersonated (for security). You can customize who can impersonate by defining `IMPERSONATE_ALLOWED` in your settings:

```python
# app/settings.py
def IMPERSONATE_ALLOWED(user):
    # Only superusers can impersonate
    return user.is_superuser
```

The impersonate URLs are included automatically with the admin router. You can check if the current request is impersonated using [`get_request_impersonator`](./impersonate/requests.py#get_request_impersonator):

```python
from plain.admin.impersonate import get_request_impersonator

def my_view(request):
    impersonator = get_request_impersonator(request)
    if impersonator:
        # The request is being impersonated
        # `impersonator` is the admin user doing the impersonating
        # `request.user` is the user being impersonated
        pass
```

## Customization

### Header branding

The top-left corner of the admin header shows your app name and an "Admin" link by default. To replace it with your own logo or branding, create an `admin/header_branding.html` template:

```html
<!-- app/templates/admin/header_branding.html -->
<a href="/">
    <img src="{{ asset('img/logo.svg') }}" alt="My App" class="h-5">
</a>
```

The template completely replaces the default branding, so include whatever links and styling you want.

### User avatar

The admin header shows a user avatar next to the account dropdown. If your User model defines a `get_avatar_url()` method, the admin will use it to display an image. Otherwise, a generic person icon is shown.

```python
# app/users/models.py
import hashlib
from plain import models
from plain.models import types


@models.register_model
class User(models.Model):
    email: str = types.EmailField()

    def get_avatar_url(self) -> str:
        # Use Gravatar
        email_hash = hashlib.md5(self.email.lower().encode("utf-8")).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon"
```

The method can return any image URL — a Gravatar, an uploaded file, or a data URI SVG.

### User menu items

To add items to the user dropdown menu (e.g., a profile page), create an `admin/user_menu_items.html` template in your app:

```html
<!-- app/templates/admin/user_menu_items.html -->
<a
    href="{{ admin_url('profile') }}"
    class="flex items-center gap-2 w-full text-left px-4 py-2 text-sm text-stone-700 hover:bg-stone-100 rounded"
>
    Profile
</a>
```

The `admin_url()` function resolves a view URL by its `path` attribute. For example, a view with `path = "profile"` is resolved by `admin_url("profile")`.

The template is included in the user dropdown before the "App Settings" and "Log out" links. If the template doesn't exist, nothing extra is shown.

## Access control

By default, any user with `is_admin=True` can access all admin views. To restrict specific views from certain admin users, use `has_permission`.

### Per-view restriction

Override `has_permission` on a view class to control who can access it. Return `False` to deny access.

```python
@register_viewset
class SensitiveDataAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = SensitiveData
        nav_section = "Internal"

        @classmethod
        def has_permission(cls, user) -> bool:
            # Only superusers can access this view
            return user.is_superuser
```

When a user is denied access to a view, they get a 403 response and the view is hidden from their navigation.

### Global restriction

To control access across all admin views (including package-shipped ones you don't own), set `ADMIN_HAS_PERMISSION` in your settings to a callable that receives the view class and user:

```python
# app/settings.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.admin.views import AdminView

    from app.users.models import User

def ADMIN_HAS_PERMISSION(view_cls: type[AdminView], user: User) -> bool:
    """Allow superusers to access all views, restrict others from package views."""
    if user.is_superuser:
        return True  # Allow access
    # Deny views from plain packages
    return not view_cls.__module__.startswith("plain.")
```

The callable should return `True` to allow access, `False` to deny it. Views can also override `has_permission` directly to implement their own logic instead of using the global setting.

## FAQs

#### How do I customize the admin templates?

Override any admin template by creating a file with the same path in your app's templates directory. For example, to customize the list view, create `app/templates/admin/list.html`.

#### How do I add a standalone admin page without a viewset?

Use `@register_view` instead of `@register_viewset`:

```python
from plain.admin.views import AdminView, register_view


@register_view
class ReportsView(AdminView):
    title = "Reports"
    path = "reports/"
    nav_section = "Analytics"
    template_name = "admin/reports.html"
```

#### How do I hide a view from the sidebar?

Set `nav_section = None` on the view class. The view will still be accessible via its URL.

#### How do I link to an object's admin page from my templates?

Use the `get_model_detail_url` function:

```python
from plain.admin.views import get_model_detail_url

url = get_model_detail_url(my_object)  # Returns None if no admin view exists
```

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
    "plain.auth.middleware.AuthMiddleware",
    "plain.admin.AdminMiddleware",
]
```

Your User model is expected to have an `is_admin` field (or attribute) for checking who has permission to access the admin.

```python
# app/users/models.py
from plain import models
from plain.models import types


@models.register_model
class User(models.Model):
    is_admin: bool = types.BooleanField(default=False)
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
        path("logout/", views.LogoutView, name="logout"),
        # other urls...
    ]
```

Create your first admin viewset for your User model:

```python
# app/users/admin.py
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import User


@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        nav_section = "Users"
        fields = ["id", "email", "is_admin", "created_at"]
        search_fields = ["email"]

    class DetailView(AdminModelDetailView):
        model = User
```

Visit `/admin/` to see your admin interface.
