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

Your settings file should be looking at the environment for secrets or other values that might change between environments. For example:

```python
# app/settings.py
STRIPE_SECRET_KEY = environ["STRIPE_SECRET_KEY"]
```

#### Local development

In local development,
you should use `.env` files to set these values.
The `.env` should then be in your `.gitignore`!

It would seem like `.env.dev` would be a good idea,
but there's a chicken-and-egg problem with that.
You would then have to prefix most (or all) of your local commands with `PLAIN_ENV=dev` or otherwise configure your environment to do that for you.
Generally speaking,
a production `.env` shouldn't be committed in your repo anyway,
so using `.env` for local development is ok.
The downside to this is that it's harder to share your local settings with others,
but these also often contain real secrets which shouldn't be committed to your repo either!
More advanced `.env` sharing patterns are currently beyond the scope of Plain...

#### Production

TODO

## Minimum required settings

```python
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = environ["SECRET_KEY"]

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

MIDDLEWARE = [
    "plain.middleware.security.SecurityMiddleware",
    "plain.assets.whitenoise.middleware.WhiteNoiseMiddleware",
    "plain.sessions.middleware.SessionMiddleware",
    "plain.middleware.common.CommonMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.middleware.clickjacking.XFrameOptionsMiddleware",
]

if DEBUG:
    INSTALLED_PACKAGES += [
        "plain.dev",
    ]
    MIDDLEWARE += [
        "plain.dev.RequestsMiddleware",
    ]

TIME_ZONE = "America/Chicago"
```
