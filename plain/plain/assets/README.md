# Assets

**Serve static assets (CSS, JS, images, etc.) directly or from a CDN.**

- [Overview](#overview)
- [Local development](#local-development)
- [Production deployment](#production-deployment)
- [Using `AssetView` directly](#using-assetview-directly)
- [FAQs](#faqs)

## Overview

To serve assets, put them in `app/assets` or `app/{package}/assets`.

Then include the [`AssetsRouter`](./urls.py#AssetsRouter) in your own router, typically under the `assets/` path.

```python
# app/urls.py
from plain.assets.urls import AssetsRouter
from plain.urls import include, Router


class AppRouter(Router):
    namespace = ""
    urls = [
        include("assets/", AssetsRouter),
        # your other routes here...
    ]
```

Now in your template you can use the `asset()` function to get the URL, which will output the fully compiled and fingerprinted URL.

```html
<link rel="stylesheet" href="{{ asset('css/style.css') }}">
```

## Local development

When you're working with `settings.DEBUG = True`, the assets will be served directly from their original location. You don't need to run `plain build` or configure anything else.

## Production deployment

In production, one of your deployment steps should be to compile the assets.

```bash
plain build
```

By default, this [generates "fingerprinted" and compressed versions of the assets](./fingerprints.py#get_file_fingerprint), which are then served by your app. This means that a file like `main.css` will result in two new files, like `main.d0db67b.css` and `main.d0db67b.css.gz`.

The purpose of fingerprinting the assets is to allow the browser to cache them indefinitely. When the content of the file changes, the fingerprint will change, and the browser will use the newer file. This cuts down on the number of requests that your app has to handle related to assets.

## Using `AssetView` directly

In some situations you may want to use the `AssetView` at a custom URL, for example to serve a `favicon.ico`. You can do this quickly by using the `AssetView.as_view()` class method.

```python
from plain.assets.views import AssetView
from plain.urls import path, Router


class AppRouter(Router):
    namespace = ""
    urls = [
        path("favicon.ico", AssetView.as_view(asset_path="favicon.ico")),
    ]
```

## FAQs

#### How do you reference assets in Python code?

There is a [`get_asset_url`](./urls.py#get_asset_url) function that you can use to get the URL of an asset in Python code. This is useful if you need to reference an asset in a non-template context, such as in a redirect or an API response.

```python
from plain.assets.urls import get_asset_url

url = get_asset_url("css/style.css")
```

#### What if I need the files in a different location?

The generated/copied files are stored in `{repo}/.plain/assets/compiled`. If you need them to be somewhere else, try simply moving them after compilation.

```bash
plain build
mv .plain/assets/compiled /path/to/your/static
```

#### How do I upload the assets to a CDN?

The steps for this will vary, but the general idea is to compile them, and then upload the compiled assets from their [compiled location](compile.py#get_compiled_path).

```bash
# Compile the assets
plain build

# List the newly compiled files
ls .plain/assets/compiled

# Upload the files to your CDN
./example-upload-to-cdn-script
```

Use the [`ASSETS_BASE_URL`](../runtime/global_settings.py#ASSETS_BASE_URL) setting to tell the `{{ asset() }}` template function where to point.

```python
# app/settings.py
ASSETS_BASE_URL = "https://cdn.example.com/"
```

#### Why aren't the originals copied to the compiled directory?

The default behavior is to fingerprint assets, which is an exact copy of the original file but with a different filename. The originals aren't copied over because you should generally always use this fingerprinted path (that automatically uses longer-lived caching).

If you need the originals for any reason, you can use `plain build --keep-original`, though this will typically be combined with `--no-fingerprint` otherwise the fingerprinted files will still get priority in `{{ asset() }}` template calls.

Note that by default, the [`ASSETS_REDIRECT_ORIGINAL`](../runtime/global_settings.py#ASSETS_REDIRECT_ORIGINAL) setting is `True`, which will redirect requests for the original file to the fingerprinted file.
