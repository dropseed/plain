# Assets

Serve static assets (CSS, JS, images, etc.) directly from your app.

The default behavior is for Plain to serve its own assets through a view. This behaves in a way similar to [Whitenoise](https://whitenoise.readthedocs.io/en/latest/).

## Usage

To include assests in your app, put them either in `app/assets` or `app/<package>/assets`.

Then include the `plain.assets.urls` in your `urls.py`:

```python
# app/urls.py
from plain.urls import include, path
import plain.assets.urls


urlpatterns = [
    path("assets/", include(plain.assets.urls)),
    # ...
]
```

Then in your template you can use the `asset()` function to get the URL.

```html
<link rel="stylesheet" href="{{ asset('css/style.css') }}">
```

If you ever need to reference an asset directly in Python code, you can use the `get_asset_url()` function.

```python
from plain.assets.urls import get_asset_url

print(get_asset_url("css/style.css"))
```
