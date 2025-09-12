# plain.redirection

**A flexible URL redirection system with admin interface and logging.**

- [Overview](#overview)
- [Basic Usage](#basic-usage)
    - [Setting up the middleware](#setting-up-the-middleware)
    - [Creating redirects](#creating-redirects)
- [Advanced Features](#advanced-features)
    - [Regex redirects](#regex-redirects)
    - [Redirect ordering](#redirect-ordering)
    - [Logging](#logging)
- [Admin Interface](#admin-interface)
- [Installation](#installation)

## Overview

`plain.redirection` provides a database-driven URL redirection system for Plain applications. It includes:

- Database models for managing redirects
- Middleware that intercepts 404s and checks for matching redirects
- Support for both exact matches and regex patterns
- Comprehensive logging of redirects and 404s
- Built-in admin interface for managing redirects

## Basic Usage

### Setting up the middleware

Add the [`RedirectionMiddleware`](./middleware.py#RedirectionMiddleware) to your middleware stack in `settings.py`:

```python
MIDDLEWARE = [
    # ... other middleware ...
    "plain.redirection.RedirectionMiddleware",
    # This should typically be near the end of the middleware stack
]
```

### Creating redirects

You can create redirects programmatically using the [`Redirect`](./models.py#Redirect) model:

```python
from plain.redirection.models import Redirect

# Simple path redirect
Redirect.query.create(
    from_pattern="/old-page/",
    to_pattern="/new-page/",
    http_status=301  # Permanent redirect
)

# Redirect with different status code
Redirect.query.create(
    from_pattern="/temporary-page/",
    to_pattern="/replacement-page/",
    http_status=302  # Temporary redirect
)
```

## Advanced Features

### Regex redirects

For more complex URL patterns, you can use regex redirects:

```python
# Redirect all blog posts to a new URL structure
Redirect.query.create(
    from_pattern=r"^/blog/(\d{4})/(\d{2})/(.+)/$",
    to_pattern=r"/posts/\1-\2-\3/",
    is_regex=True,
    http_status=301
)
```

### Redirect ordering

When multiple redirects might match a URL, you can control which one takes precedence using the `order` field:

```python
# This redirect will be checked first (lower order = higher priority)
Redirect.query.create(
    from_pattern="/special-case/",
    to_pattern="/handled-specially/",
    order=10
)

# This more general redirect will be checked later
Redirect.query.create(
    from_pattern=r"^/special-.*/$",
    to_pattern="/general-handler/",
    is_regex=True,
    order=20
)
```

### Logging

The package automatically logs all redirects and 404s:

- [`RedirectLog`](./models.py#RedirectLog) - Records successful redirects with request metadata
- [`NotFoundLog`](./models.py#NotFoundLog) - Records 404s that didn't match any redirect

Access logs programmatically:

```python
from plain.redirection.models import RedirectLog, NotFoundLog

# Recent redirects
recent_redirects = RedirectLog.query.all()[:10]

# 404s from a specific IP
not_founds = NotFoundLog.query.filter(ip_address="192.168.1.1")
```

## Admin Interface

The package includes admin views for managing redirects and viewing logs. Once installed, you'll find three new sections in your admin:

- **Redirects** - Create, edit, and delete redirect rules
- **Redirect logs** - View successful redirects with full request details
- **404 logs** - Monitor URLs that resulted in 404s

The admin interface is automatically registered and will appear in the "Redirection" section of your Plain admin.

## Installation

Install the `plain.redirection` package from [PyPI](https://pypi.org/project/plain.redirection/):

```bash
uv add plain.redirection
```
