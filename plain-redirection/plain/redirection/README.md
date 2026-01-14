# plain.redirection

**Database-driven URL redirects with logging and admin interface.**

- [Overview](#overview)
- [Creating redirects](#creating-redirects)
- [Regex patterns](#regex-patterns)
- [Full URL matching](#full-url-matching)
- [Logs](#logs)
    - [Automatic cleanup](#automatic-cleanup)
- [Admin interface](#admin-interface)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can manage URL redirects through the database instead of hardcoding them in your URL configuration. When a request results in a 404, the [`RedirectionMiddleware`](./middleware.py#RedirectionMiddleware) checks for a matching redirect rule and sends the user to the new location.

```python
from plain.redirection.models import Redirect

# Create a simple redirect
Redirect.query.create(
    from_pattern="/old-page/",
    to_pattern="/new-page/",
    http_status=301,  # Permanent redirect (default)
)
```

All redirects are logged automatically, and 404s that don't match any redirect are logged separately. You can view and manage everything through the built-in admin interface.

## Creating redirects

The [`Redirect`](./models.py#Redirect) model stores your redirect rules. Each redirect has a `from_pattern` to match against and a `to_pattern` to redirect to.

```python
# Temporary redirect (302)
Redirect.query.create(
    from_pattern="/sale/",
    to_pattern="/promotions/summer-sale/",
    http_status=302,
)

# Disable a redirect without deleting it
redirect = Redirect.query.get(from_pattern="/old-page/")
redirect.enabled = False
redirect.save()
```

When multiple redirects could match, you can control priority with the `order` field. Lower values are checked first.

```python
# This redirect is checked first
Redirect.query.create(
    from_pattern="/blog/featured/",
    to_pattern="/featured-posts/",
    order=10,
)

# This more general pattern is checked later
Redirect.query.create(
    from_pattern="/blog/",
    to_pattern="/articles/",
    order=20,
)
```

## Regex patterns

For dynamic URL patterns, set `is_regex=True` and use regex groups in your patterns.

```python
# Redirect /blog/2024/01/my-post/ to /posts/2024-01-my-post/
Redirect.query.create(
    from_pattern=r"^/blog/(\d{4})/(\d{2})/(.+)/$",
    to_pattern=r"/posts/\1-\2-\3/",
    is_regex=True,
)
```

The `to_pattern` can reference captured groups from the `from_pattern` using `\1`, `\2`, etc.

## Full URL matching

By default, patterns match against the request path (e.g., `/old-page/`). If your pattern starts with `http`, it matches against the full URL including the domain and query string.

```python
# Redirect requests from a specific domain
Redirect.query.create(
    from_pattern="https://old-domain.com/page/",
    to_pattern="/page/",
)
```

## Logs

Every redirect is recorded in [`RedirectLog`](./models.py#RedirectLog), capturing the original URL, destination, and request metadata like IP address, user agent, and referrer.

```python
from plain.redirection.models import RedirectLog

# Recent redirects
recent = RedirectLog.query.all()[:10]

for log in recent:
    print(f"{log.from_url} -> {log.to_url} ({log.ip_address})")
```

Requests that result in 404s (and don't match any redirect) are logged in [`NotFoundLog`](./models.py#NotFoundLog).

```python
from plain.redirection.models import NotFoundLog

# Find 404s from a specific referrer
broken_links = NotFoundLog.query.filter(referrer__contains="external-site.com")
```

### Automatic cleanup

Logs are automatically cleaned up by the [`DeleteLogs`](./chores.py#DeleteLogs) chore. By default, logs older than 30 days are deleted. You can customize this in your settings:

```python
# app/settings.py
from datetime import timedelta

REDIRECTION_LOG_RETENTION_TIMEDELTA = timedelta(days=90)
```

## Admin interface

The package includes admin views for managing redirects and viewing logs. Once installed, you will find three sections under "Redirection" in your admin:

- **Redirects** - Create, edit, and delete redirect rules
- **Redirect logs** - View successful redirects with request details
- **404 logs** - Monitor URLs that resulted in 404s

The 404 logs are useful for discovering broken links on your site. You can search the logs to find patterns and create redirects to fix them.

## FAQs

#### How does the middleware decide when to redirect?

The middleware only checks for redirects when a request results in a 404. It iterates through enabled redirects (ordered by the `order` field, then by creation date) and returns the first match. If no redirect matches, the 404 is logged and the original response is returned.

#### Can I redirect to external URLs?

Yes. The `to_pattern` can be any URL, including external sites:

```python
Redirect.query.create(
    from_pattern="/partner/",
    to_pattern="https://partner-site.com/landing/",
)
```

#### What HTTP status codes can I use?

Any valid HTTP redirect status code works. The most common are:

- `301` - Permanent redirect (default). Search engines update their index.
- `302` - Temporary redirect. Search engines keep the original URL.
- `307` - Temporary redirect that preserves the request method.
- `308` - Permanent redirect that preserves the request method.

## Installation

Install the `plain.redirection` package from [PyPI](https://pypi.org/project/plain.redirection/):

```console
uv add plain.redirection
```

Add `plain.redirection` to your `INSTALLED_PACKAGES` in `app/settings.py`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...other packages
    "plain.redirection",
]
```

Add the middleware to your `MIDDLEWARE` setting. It should be near the end so other middleware can process requests first:

```python
# app/settings.py
MIDDLEWARE = [
    # ...other middleware
    "plain.redirection.RedirectionMiddleware",
]
```

Run migrations to create the database tables:

```console
plain migrate
```

You can now create redirects through the admin interface or programmatically using the `Redirect` model.
