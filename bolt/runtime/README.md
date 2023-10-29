# Runtime

Leverage user-settings at runtime.

## Settings

### Single-file

All of your settings go in `app/settings.py`.
That's how you do it!

The file itself is not much different than how Django does it,
but the location,
and a strong recommendation to only use the one file makes a big difference.

### Environment variables

It seems pretty well-accepted these days that storing settings in env vars is a good idea ([12factor.net](https://12factor.net/config)).

Your settings file should be looking at the environment for secrets or other values that might change between environments.

In local development,
you should use `.env` files to set these values.

## Minimum required settings

```python
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = environ["SECRET_KEY"]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.assets.whitenoise.middleware.WhiteNoiseMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "bolt.auth.middleware.AuthenticationMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    INSTALLED_PACKAGES += [
        "bolt.dev",
    ]
    MIDDLEWARE += [
        "bolt.dev.RequestsMiddleware",
    ]

TIME_ZONE = "America/Chicago"
```
