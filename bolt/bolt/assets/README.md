# Assets

Serve static assets (CSS, JS, images, etc.) for your app.

The default behavior is for Bolt to serve assets directly via a middleware.
This is based on [whitenoise](http://whitenoise.evans.io/en/stable/).

## Usage

Generally speaking, the simplest way to include assests in your app is to put them either in `app/assets` or `app/<package>/assets`.

Then in your template you can use the `asset()` function to get the URL.

```html
<link rel="stylesheet" href="{{ asset('css/style.css') }}">
```

If you ever need to reference an asset directly in Python code, you can use the `get_asset_url()` function.

```python
from bolt.assets import get_asset_url

print(get_asset_url("css/style.css"))
```

## Settings

These are the default settings related to assets handling.

```python
# app/settings.py
MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.assets.whitenoise.middleware.WhiteNoiseMiddleware",  # <--
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
]

ASSETS_BACKEND = "bolt.assets.whitenoise.storage.CompressedManifestStaticFilesStorage"

# List of finder classes that know how to find assets files in
# various locations.
ASSETS_FINDERS = [
    "bolt.assets.finders.FileSystemFinder",
    "bolt.assets.finders.PackageDirectoriesFinder",
]

# Absolute path to the directory assets files should be collected to.
# Example: "/var/www/example.com/assets/"
ASSETS_ROOT = BOLT_TEMP_PATH / "assets_collected"

# URL that handles the assets files served from ASSETS_ROOT.
# Example: "http://example.com/assets/", "http://assets.example.com/"
ASSETS_URL = "/assets/"
```
