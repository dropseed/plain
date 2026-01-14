# URLs

**Route incoming requests to views based on URL patterns.**

- [Overview](#overview)
- [Defining paths](#defining-paths)
- [Including sub-routers](#including-sub-routers)
- [Path converters](#path-converters)
    - [Built-in converters](#built-in-converters)
    - [Custom converters](#custom-converters)
- [Reversing URLs](#reversing-urls)
    - [In templates](#in-templates)
    - [In Python code](#in-python-code)
    - [Lazy reverse](#lazy-reverse)
- [Regex patterns](#regex-patterns)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You define URL routing by creating a `Router` class with a list of URL patterns. Each pattern maps a URL path to a view.

```python
# app/urls.py
from plain.urls import Router, path
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", views.HomeView),
        path("about/", views.AboutView, name="about"),
        path("contact/", views.ContactView, name="contact"),
    ]
```

The `URLS_ROUTER` setting in your `app/settings.py` tells Plain which router handles incoming requests:

```python
# app/settings.py
URLS_ROUTER = "app.urls.AppRouter"
```

When a request comes in, Plain matches the URL against your patterns in order and calls the corresponding view.

## Defining paths

Use `path()` to map a URL pattern to a view class:

```python
path("about/", views.AboutView, name="about")
```

The `name` parameter is optional but required if you want to reverse the URL later. You can pass the view class directly (Plain calls `as_view()` for you) or call `as_view()` yourself to pass arguments:

```python
path("dashboard/", views.DashboardView.as_view(template_name="custom.html"), name="dashboard")
```

## Including sub-routers

Use `include()` to nest routers under a URL prefix. This keeps your URL configuration modular.

```python
from plain.urls import Router, path, include
from plain.admin.urls import AdminRouter
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        include("api/", ApiRouter),
        path("", views.HomeView),
    ]
```

Each included router has its own `namespace` that prefixes URL names. For example, if `AdminRouter` has `namespace = "admin"` and a URL named `"dashboard"`, you reverse it as `"admin:dashboard"`.

You can also include a list of patterns directly without creating a separate router class:

```python
include("api/", [
    path("users/", views.UsersAPIView, name="users"),
    path("posts/", views.PostsAPIView, name="posts"),
])
```

## Path converters

Capture dynamic segments from URLs using angle bracket syntax:

```python
path("user/<int:user_id>/", views.UserView, name="user")
path("post/<slug:post_slug>/", views.PostView, name="post")
```

Captured values are available in your view as `self.url_kwargs`:

```python
class UserView(View):
    def get(self):
        user_id = self.url_kwargs["user_id"]  # Already converted to int
        # ...
```

### Built-in converters

| Converter | Matches                                                 | Python type |
| --------- | ------------------------------------------------------- | ----------- |
| `str`     | Any non-empty string excluding `/` (default)            | `str`       |
| `int`     | Zero or positive integers                               | `int`       |
| `slug`    | ASCII letters, numbers, hyphens, underscores            | `str`       |
| `uuid`    | UUID format like `075194d3-6885-417e-a8a8-6c931e272f00` | `uuid.UUID` |
| `path`    | Any non-empty string including `/`                      | `str`       |

When no converter is specified, `str` is used:

```python
path("search/<query>/", views.SearchView)  # Same as <str:query>
```

### Custom converters

You can register your own converters using [`register_converter()`](./converters.py#register_converter). A converter class needs a `regex` attribute and `to_python()` / `to_url()` methods:

```python
from plain.urls import register_converter


class YearConverter:
    regex = "[0-9]{4}"

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)


register_converter(YearConverter, "year")
```

Then use it in your patterns:

```python
path("archive/<year:year>/", views.ArchiveView, name="archive")
```

## Reversing URLs

### In templates

Use the `url()` function to generate URLs by name:

```html
<a href="{{ url('about') }}">About</a>
<a href="{{ url('user', user_id=42) }}">User Profile</a>
<a href="{{ url('admin:dashboard') }}">Admin Dashboard</a>
```

### In Python code

Use `reverse()` to generate URLs programmatically:

```python
from plain.urls import reverse

url = reverse("about")  # "/about/"
url = reverse("user", user_id=42)  # "/user/42/"
url = reverse("admin:dashboard")  # "/admin/dashboard/"
```

If the URL name does not exist or the arguments do not match, `reverse()` raises [`NoReverseMatch`](./exceptions.py#NoReverseMatch).

### Lazy reverse

Use `reverse_lazy()` when you need a URL at module load time (such as in class attributes or default arguments):

```python
from plain.urls import reverse_lazy


class MyView(View):
    success_url = reverse_lazy("home")
```

The URL is not resolved until it is actually used as a string.

## Regex patterns

For complex matching that path converters cannot handle, you can use regular expressions:

```python
import re
from plain.urls import path

path(re.compile(r"^articles/(?P<year>[0-9]{4})/$"), views.ArticleView, name="article")
```

Named groups become keyword arguments. Unnamed groups become positional arguments accessible via `self.url_args`.

## FAQs

#### Why does my URL pattern need a trailing slash?

By default, Plain's `APPEND_SLASH` setting redirects URLs without a trailing slash to URLs with one. Define your patterns with trailing slashes to match this behavior. If you prefer URLs without trailing slashes, set `APPEND_SLASH = False` in your settings.

#### How do I debug URL routing issues?

Check that your URL patterns are in the correct order. Plain matches patterns top to bottom and uses the first match. More specific patterns should come before general ones.

#### Can I access URL arguments as positional args instead of kwargs?

If you use regex patterns with unnamed groups (no `?P<name>`), values are passed as positional arguments in `self.url_args`. Named groups always populate `self.url_kwargs`.

## Installation

The `plain.urls` module is included with Plain by default. No additional installation is required.

To set up URL routing, create a router in `app/urls.py` and point to it in your settings:

```python
# app/settings.py
URLS_ROUTER = "app.urls.AppRouter"
```

```python
# app/urls.py
from plain.urls import Router, path
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", views.HomeView),
    ]
```
