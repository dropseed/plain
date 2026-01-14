# plain.utils

**Common utilities for working with dates, text, HTML, and more.**

- [Overview](#overview)
- [Timezone utilities](#timezone-utilities)
    - [Getting the current time](#getting-the-current-time)
    - [Converting between aware and naive datetimes](#converting-between-aware-and-naive-datetimes)
    - [Temporarily changing the timezone](#temporarily-changing-the-timezone)
- [Time formatting](#time-formatting)
- [Text utilities](#text-utilities)
    - [Slugify](#slugify)
    - [Truncating text](#truncating-text)
- [HTML utilities](#html-utilities)
    - [Escaping HTML](#escaping-html)
    - [Formatting HTML safely](#formatting-html-safely)
    - [Stripping tags](#stripping-tags)
    - [Embedding JSON in HTML](#embedding-json-in-html)
- [Safe strings](#safe-strings)
- [Random strings](#random-strings)
- [Date parsing](#date-parsing)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain.utils` module provides a collection of utilities that you'll commonly need when building web applications. You can import what you need directly from the submodules:

```python
from plain.utils.timezone import now, localtime
from plain.utils.text import slugify
from plain.utils.html import escape, format_html

# Get the current time as a timezone-aware datetime
current_time = now()

# Create a URL-safe slug
slug = slugify("Hello World!")  # "hello-world"

# Safely format HTML with escaped values
html = format_html("<p>Hello, {}!</p>", user_input)
```

## Timezone utilities

Plain uses timezone-aware datetimes throughout. The timezone utilities help you work with aware datetimes consistently.

### Getting the current time

```python
from plain.utils.timezone import now

current_time = now()  # Returns a timezone-aware datetime in UTC
```

### Converting between aware and naive datetimes

```python
from plain.utils.timezone import make_aware, make_naive, is_aware, localtime
from datetime import datetime

# Check if a datetime is aware
is_aware(some_datetime)

# Make a naive datetime aware (uses current timezone by default)
aware_dt = make_aware(datetime(2024, 1, 15, 10, 30))

# Convert to local time
local_dt = localtime(aware_dt)

# Make an aware datetime naive
naive_dt = make_naive(aware_dt)
```

### Temporarily changing the timezone

```python
from plain.utils.timezone import override, get_current_timezone

with override("America/New_York"):
    # Code here uses the New York timezone
    tz = get_current_timezone()
```

For more timezone functions, see [`timezone.py`](./timezone.py#activate).

## Time formatting

Format time differences as human-readable strings.

```python
from plain.utils.timesince import timesince, timeuntil
from datetime import datetime, timedelta
from plain.utils.timezone import now

past = now() - timedelta(days=2, hours=3)
timesince(past)  # "2 days, 3 hours"

future = now() + timedelta(weeks=1)
timeuntil(future)  # "1 week"
```

You can use a short format for compact display:

```python
timesince(past, format="short")  # "2d 3h"
```

## Text utilities

### Slugify

Convert text to a URL-safe slug.

```python
from plain.utils.text import slugify

slugify("Hello World!")  # "hello-world"
slugify("Cafe au lait")  # "cafe-au-lait"
slugify("My Article Title")  # "my-article-title"

# Preserve unicode characters
slugify("Ich liebe Berlin", allow_unicode=True)  # "ich-liebe-berlin"
```

### Truncating text

Truncate text by characters or words, with HTML support.

```python
from plain.utils.text import Truncator

text = "This is a long piece of text that needs to be shortened."
Truncator(text).chars(20)  # "This is a long pie..."
Truncator(text).words(5)   # "This is a long piece..."

# Truncate HTML while preserving valid structure
html = "<p>This is <strong>bold</strong> text.</p>"
Truncator(html).chars(15, html=True)  # "<p>This is <strong>bo</strong>...</p>"
```

## HTML utilities

### Escaping HTML

```python
from plain.utils.html import escape

escape("<script>alert('xss')</script>")
# "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;"
```

### Formatting HTML safely

Build HTML fragments with automatic escaping of values:

```python
from plain.utils.html import format_html

# Values are automatically escaped
format_html("<a href='{}'>{}</a>", url, link_text)

# Safe for untrusted input
format_html("<p>Welcome, {}!</p>", user_provided_name)
```

### Stripping tags

Remove HTML tags from text:

```python
from plain.utils.html import strip_tags

strip_tags("<p>Hello <strong>world</strong>!</p>")  # "Hello world!"
```

### Embedding JSON in HTML

Safely embed JSON data in a script tag:

```python
from plain.utils.html import json_script

data = {"user": "john", "count": 42}
json_script(data, element_id="user-data")
# '<script id="user-data" type="application/json">{"user": "john", "count": 42}</script>'
```

## Safe strings

Mark strings as safe to prevent double-escaping.

```python
from plain.utils.safestring import mark_safe, SafeString

# Mark a string as already escaped/safe
html = mark_safe("<strong>Already safe HTML</strong>")

# Check if something is a SafeString
isinstance(html, SafeString)  # True
```

Use `mark_safe` only when you've manually ensured the content is safe. For building HTML from untrusted input, use `format_html` instead.

## Random strings

Generate cryptographically secure random strings.

```python
from plain.utils.crypto import get_random_string

# Default: 12 characters, alphanumeric
token = get_random_string(12)  # e.g., "Kx9mP2nL4qRs"

# Custom character set
pin = get_random_string(6, allowed_chars="0123456789")  # e.g., "847293"
```

## Date parsing

Parse date and time strings into Python objects.

```python
from plain.utils.dateparse import parse_date, parse_datetime, parse_time, parse_duration

parse_date("2024-01-15")  # datetime.date(2024, 1, 15)
parse_datetime("2024-01-15T10:30:00Z")  # datetime.datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
parse_time("10:30:00")  # datetime.time(10, 30)
parse_duration("1 02:30:00")  # datetime.timedelta(days=1, hours=2, minutes=30)
```

These functions return `None` if the input is not well-formatted, and raise `ValueError` if the input is well-formatted but invalid.

## FAQs

#### What about the other utilities in this module?

The `plain.utils` module contains additional utilities that are primarily used internally by Plain. You can explore the source files directly:

- [`datastructures.py`](./datastructures.py) - `MultiValueDict`, `OrderedSet`, `ImmutableList`
- [`functional.py`](./functional.py) - `SimpleLazyObject`, `lazy`, `classproperty`
- [`http.py`](./http.py) - `urlencode`, `http_date`, `base36_to_int`
- [`encoding.py`](./encoding.py) - `force_str`, `force_bytes`

#### Should I use `datetime.datetime.now()` or `plain.utils.timezone.now()`?

Always use `plain.utils.timezone.now()`. It returns a timezone-aware datetime in UTC, which is what Plain expects throughout the framework.

## Installation

The `plain.utils` module is included with Plain.

```python
from plain.utils.timezone import now
from plain.utils.text import slugify
```
