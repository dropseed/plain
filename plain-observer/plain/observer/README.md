# plain.observer

**On-page telemetry and observability tools for Plain.**

## Installation

```bash
uv add plain.observer
```

Add `plain.observer` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.observer",
]
```

Include the observer URLs in your URL configuration:

```python
# app/urls.py
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        # ...
        include("observer/", "plain.observer.urls"),
    ]
```

Run migrations to create the necessary database tables:

```bash
plain migrate
```
