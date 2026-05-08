# Exercises annotation resolution for annotation-only APP_ settings (the
# `from __future__` import turns `APP_FOO: int` into the string "int").
from __future__ import annotations

SECRET_KEY = "secret"
DEBUG = True

URLS_ROUTER = "app.urls.AppRouter"

INSTALLED_PACKAGES = [
    "app.test",
]

EXPLICIT_SETTING = "explicitly changed"
EXPLICIT_OVERRIDDEN_SETTING = "explicit value"

# Annotation-only custom settings — required, supplied via
# PLAIN_APP_* env vars set in conftest.py.
APP_REQUIRED_FROM_ENV: str
APP_REQUIRED_TYPED_FROM_ENV: int
