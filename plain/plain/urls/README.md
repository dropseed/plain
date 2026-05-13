# URLs

**Route incoming requests to views based on URL patterns.**

- [Overview](#overview)
- [Defining paths](#defining-paths)
- [Including sub-routers](#including-sub-routers)
- [Path converters](#path-converters)
- [Trailing slashes](#trailing-slashes)
- [Reversing URLs](#reversing-urls)
    - [In templates](#in-templates)
    - [In Python code](#in-python-code)
    - [Lazy reverse](#lazy-reverse)
- [Absolute URLs](#absolute-urls)
    - [Setting up BASE_URL](#setting-up-base_url)
    - [In templates](#in-templates-1)
    - [In Python code](#in-python-code-1)
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
        path("about", views.AboutView, name="about"),
        path("contact", views.ContactView, name="contact"),
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
path("about", views.AboutView, name="about")
```

The `name` parameter is optional but required if you want to reverse the URL later. Plain instantiates the view class per request — to customize a view for a specific route, subclass it and set class attributes:

```python
class CustomDashboardView(views.DashboardView):
    template_name = "custom.html"


path("dashboard", CustomDashboardView, name="dashboard")
```

The trailing slash on the route string is stripped silently — `path("about", ...)` and `path("about/", ...)` produce identical routes. Whether the canonical URL has a trailing slash is controlled by the app-wide [`URLS_TRAILING_SLASH`](#trailing-slashes) setting (default `False`), with `force_trailing_slash=True|False` as a per-route override.

## Including sub-routers

Use `include()` to nest routers under a URL prefix. This keeps your URL configuration modular.

```python
from plain.urls import Router, path, include
from plain.admin.urls import AdminRouter
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin", AdminRouter),
        include("api", ApiRouter),
        path("", views.HomeView),
    ]
```

Each included router has its own `namespace` that prefixes URL names. For example, if `AdminRouter` has `namespace = "admin"` and a URL named `"dashboard"`, you reverse it as `"admin:dashboard"`.

You can also include a list of patterns directly without creating a separate router class:

```python
include("api", [
    path("users", views.UsersAPIView, name="users"),
    path("posts", views.PostsAPIView, name="posts"),
])
```

## Path converters

Capture dynamic segments from URLs using angle bracket syntax:

```python
path("user/<int:user_id>", views.UserView, name="user")
path("post/<slug:post_slug>", views.PostView, name="post")
```

Captured values are available in your view as `self.url_kwargs`:

```python
class UserView(View):
    def get(self):
        user_id = self.url_kwargs["user_id"]  # Already converted to int
        # ...
```

The available converters are:

| Converter | Matches                                                 | Python type |
| --------- | ------------------------------------------------------- | ----------- |
| `str`     | Any non-empty string excluding `/` (default)            | `str`       |
| `int`     | Zero or positive integers                               | `int`       |
| `slug`    | ASCII letters, numbers, hyphens, underscores            | `str`       |
| `uuid`    | UUID format like `075194d3-6885-417e-a8a8-6c931e272f00` | `uuid.UUID` |
| `path`    | Any non-empty string including `/`                      | `str`       |

When no converter is specified, `str` is used:

```python
path("search/<query>", views.SearchView)  # Same as <str:query>
```

Converters validate but don't normalize the URL text itself — `int` matches `001` just as it matches `1`, and `self.url_kwargs["id"]` returns `1`. `reverse()` renders the integer back as `"1"`, so a round-trip from `/users/001` does not preserve leading zeros. Use `slug` or `str` if you need the captured text to round-trip unchanged.

## Trailing slashes

Trailing slashes are an app-wide concept driven by the `URLS_TRAILING_SLASH` setting:

```python
# app/settings.py
URLS_TRAILING_SLASH = False  # default — `/about` is canonical
# or
URLS_TRAILING_SLASH = True   # `/about/` is canonical
```

The slash on the route string is irrelevant — `path("about")` and `path("about/")` produce identical routes; the canonical form is decided by the setting. Requests at the non-canonical form 308-redirect to the canonical one (308 preserves the HTTP method and body across the redirect).

Catchall routes (`path("<path:NAME>")`) are slash-agnostic — they absorb the request trailing slash into the captured value and never redirect.

### Per-route override

Use `force_trailing_slash` to opt a single route out of the global setting:

```python
# `URLS_TRAILING_SLASH = True`, but this one route serves `/sitemap.xml` (no slash)
path("sitemap.xml", views.SitemapView, force_trailing_slash=False)

# `URLS_TRAILING_SLASH = False`, but this one route serves `/admin/` (slash)
path("admin", views.LegacyAdminView, force_trailing_slash=True)
```

`force_trailing_slash=None` (the default) means "follow the setting." Useful for file-extension routes that should never have a slash (`sitemap.xml`, `robots.txt`, `favicon.ico`) when the rest of the app uses slashes, or for keeping a legacy URL stable.

## Reversing URLs

### In templates

Use `url()` to generate URLs by name (`url` is a template alias for `reverse`):

```html
<a href="{{ url('about') }}">About</a>
<a href="{{ url('user', user_id=42) }}">User Profile</a>
<a href="{{ url('admin:dashboard') }}">Admin Dashboard</a>
```

### In Python code

Use `reverse()` to generate URLs programmatically:

```python
from plain.urls import reverse

url = reverse("about")  # "/about" (or "/about/" under URLS_TRAILING_SLASH=True)
url = reverse("user", user_id=42)  # "/user/42"
url = reverse("admin:dashboard")  # "/admin/dashboard"
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

## Absolute URLs

Generate full URLs that include the scheme and domain. This is useful for links in emails, background jobs, API responses, Open Graph tags, and anywhere else you need a complete URL.

### Setting up BASE_URL

Set the `BASE_URL` setting to your site's root URL (scheme + host, no trailing slash):

```python
# app/settings.py
BASE_URL = "https://example.com"
```

If `BASE_URL` is not configured, calling `absolute_url()` or `reverse_absolute()` will raise a `ValueError`.

### In templates

Use `reverse_absolute()` — the absolute version of `reverse()`. It takes the same arguments (a URL name and optional parameters) and returns a full URL:

```html
<a href="{{ url('article', slug=article.slug) }}">Read more</a>
<meta property="og:url" content="{{ reverse_absolute('article', slug=article.slug) }}">
```

### In Python code

Use `reverse_absolute()` to reverse a URL name into a full URL:

```python
from plain.urls import reverse_absolute

url = reverse_absolute("user", user_id=42)  # "https://example.com/user/42"
```

Use `absolute_url()` when you already have a path (e.g. from `get_absolute_url()`):

```python
from plain.urls import absolute_url

url = absolute_url(article.get_absolute_url())  # "https://example.com/articles/hello-world"
```

## FAQs

#### Does my URL pattern need a trailing slash?

No — the slash on the route string is stripped silently. Trailing-slash behavior is set app-wide by `URLS_TRAILING_SLASH` (default `False`), with `force_trailing_slash=True|False` as a per-route override. See [Trailing slashes](#trailing-slashes).

#### What happens to `//`, `.`, or `..` in request paths?

Plain normalizes them before route matching, per RFC 3986:

- `/foo//bar` collapses to `/foo/bar` (308 redirect)
- `/foo/./bar` resolves to `/foo/bar` (308 redirect)
- `/foo/../bar` resolves to `/bar` (308 redirect)
- `/../foo` returns 400 — `..` can't resolve below the root

Your URL patterns never see non-canonical paths.

#### How do I debug URL routing issues?

Check that your URL patterns are in the correct order. Plain matches patterns top to bottom and uses the first match. More specific patterns should come before general ones.

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
