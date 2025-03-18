# URLs

**Route requests to views.**

URLs are typically the "entrypoint" to your app. Virtually all request handling up to this point happens behind the scenes, and then you decide how to route specific URL patterns to your views.

The `URLS_ROUTER` is the primary router that handles all incoming requests. It is defined in your `app/settings.py` file. This will typically point to a `Router` class in your `app.urls` module.

```python
# app/settings.py
URLS_ROUTER = "app.urls.AppRouter"
```

The root router often has an empty namespace (`""`) and some combination of individual paths and sub-routers.

```python
# app/urls.py
from plain.urls import Router, path, include
from plain.admin.urls import AdminRouter
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        path("about/", views.AboutView, name="about"),  # A named URL
        path("", views.HomeView),  # An unnamed URL
    ]
```

## Reversing URLs

In templates, you will use the `{{ url("<url name>") }}` function to look up full URLs by name.

```html
<a href="{{ url('about') }}">About</a>
```

And the same can be done in Python code with the `reverse` (or `reverse_lazy`) function.

```python
from plain.urls import reverse

url = reverse("about")
```

A URL path has to include a `name` attribute if you want to reverse it. The router's `namespace` will be used as a prefix to the URL name.

```python
from plain.urls import reverse

url = reverse("admin:dashboard")
```

## URL args and kwargs

URL patterns can include arguments and keyword arguments.

```python
# app/urls.py
from plain.urls import Router, path
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        path("user/<int:user_id>/", views.UserView, name="user"),
        path("search/<str:query>/", views.SearchView, name="search"),
    ]
```

These will be accessible inside the view as `self.url_args` and `self.url_kwargs`.

```python
# app/views.py
from plain.views import View


class SearchView(View):
    def get(self):
        query = self.url_kwargs["query"]
        print(f"Searching for {query}")
        # ...
```

To reverse a URL with args or kwargs, simply pass them in the `reverse` function.

```python
from plain.urls import reverse

url = reverse("search", query="example")
```

There are a handful of built-in [converters](converters.py#DEFAULT_CONVERTERS) that can be used in URL patterns.

```python
from plain.urls import Router, path
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        path("user/<int:user_id>/", views.UserView, name="user"),
        path("search/<str:query>/", views.SearchView, name="search"),
        path("post/<slug:post_slug>/", views.PostView, name="post"),
        path("document/<uuid:uuid>/", views.DocumentView, name="document"),
        path("path/<path:subpath>/", views.PathView, name="path"),
    ]
```

## Package routers

Installed packages will often provide a URL router to include in your root URL router.

```python
# plain/assets/urls.py
from plain.urls import Router, path
from .views import AssetView


class AssetsRouter(Router):
    """
    The router for serving static assets.

    Include this router in your app router if you are serving assets yourself.
    """

    namespace = "assets"
    urls = [
        path("<path:path>", AssetView, name="asset"),
    ]
```

Import the package's router and `include` it at any path you choose.

```python
from plain.urls import include, Router
from plain.assets.urls import AssetsRouter


class AppRouter(Router):
    namespace = ""
    urls = [
        include("assets/", AssetsRouter),
        # Your other URLs here...
    ]
```
