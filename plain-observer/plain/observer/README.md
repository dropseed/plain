# plain.observer

**Request tracing and debugging tools built on OpenTelemetry.**

- [Overview](#overview)
- [Observer modes](#observer-modes)
    - [Summary mode](#summary-mode)
    - [Persist mode](#persist-mode)
    - [Disabled mode](#disabled-mode)
- [Toolbar integration](#toolbar-integration)
- [CLI commands](#cli-commands)
- [Admin integration](#admin-integration)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use Observer to trace requests and debug performance issues in your Plain application. Observer integrates with OpenTelemetry to capture spans, database queries, and logs for individual requests.

When enabled, Observer shows you a real-time summary of each request including query counts, duplicate queries, and total duration. You can also persist traces to the database for later analysis.

```python
# Access the Observer from any request
from plain.observer import Observer

observer = Observer.from_request(request)

# Check the current mode
if observer.is_enabled():
    print("Observer is tracking this request")

if observer.is_persisting():
    print("Traces will be saved to the database")

# Get a summary of the current trace
summary = observer.get_current_trace_summary()
# Returns something like: "5 queries (2 duplicates) • 45.2ms"
```

The [`Observer`](./core.py#Observer) class provides methods to check the current mode and enable/disable tracing via cookies.

## Observer modes

Observer has three modes that control how traces are captured.

### Summary mode

Summary mode captures spans in memory for real-time monitoring but does not save them to the database. This is useful for debugging during development without filling up your database.

```python
from plain.observer import Observer

def my_view(request):
    observer = Observer.from_request(request)
    response = Response("OK")
    observer.enable_summary_mode(response)
    return response
```

The summary cookie lasts for 1 week.

### Persist mode

Persist mode captures spans and saves them to the database. This includes full trace data, spans, and log entries. Use this when you need to analyze traces after the request completes.

```python
observer.enable_persist_mode(response)
```

The persist cookie lasts for 1 day.

### Disabled mode

You can explicitly disable Observer to prevent any tracing, even if a parent trace exists.

```python
observer.disable(response)
```

## Toolbar integration

If you have `plain.toolbar` installed, Observer automatically adds a panel showing the current mode and trace summary. You can toggle between modes directly from the toolbar.

The toolbar panel displays:

- Current observer mode (Summary, Persist, or Disabled)
- Query count with duplicate detection
- Total request duration
- Link to view persisted traces

## CLI commands

Observer provides CLI commands for managing and viewing traces.

```bash
# List recent traces
plain observer traces
plain observer traces --limit 50
plain observer traces --user-id 123
plain observer traces --json

# View a specific trace
plain observer trace <trace_id>
plain observer trace <trace_id> --json

# List spans
plain observer spans
plain observer spans --trace-id <trace_id>

# View a specific span
plain observer span <span_id>

# Clear all trace data
plain observer clear
plain observer clear --force
```

The `traces` and `spans` commands support filtering by user ID, session ID, or request ID, and can output JSON for programmatic use.

## Admin integration

When `plain.admin` is installed, Observer registers viewsets for browsing Traces, Spans, and Logs. You can find these under the "Observer" section in the admin navigation.

The admin views let you:

- Browse and search traces by request ID, user ID, or session ID
- View span hierarchies and timing
- Filter spans by parent status
- Search and filter log entries by level or message

## Settings

| Setting                        | Default | Env var                                     |
| ------------------------------ | ------- | ------------------------------------------- |
| `OBSERVER_IGNORE_URL_PATTERNS` | `[...]` | `PLAIN_OBSERVER_IGNORE_URL_PATTERNS` (JSON) |
| `OBSERVER_TRACE_LIMIT`         | `100`   | `PLAIN_OBSERVER_TRACE_LIMIT`                |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I enable Observer in production?

Observer is controlled by a signed cookie, so you can enable it for specific users or sessions. The toolbar provides an easy way to toggle modes, or you can set the cookie programmatically in a view.

#### Can I use Observer with an external OpenTelemetry collector?

Yes. Observer uses the [`ObserverSampler`](./otel.py#ObserverSampler) and [`ObserverSpanProcessor`](./otel.py#ObserverSpanProcessor) which integrate with OpenTelemetry's standard APIs. You can combine Observer with other samplers using [`ObserverCombinedSampler`](./otel.py#ObserverCombinedSampler).

#### Why are some URLs not being traced?

Observer ignores certain URL patterns by default (assets, observer routes, etc.) to reduce noise. You can customize this with the `OBSERVER_IGNORE_URL_PATTERNS` setting.

#### How do I get the trace summary in a template?

In persist or summary mode, you can access the summary from the Observer instance:

```python
# In your view
context["trace_summary"] = Observer.from_request(request).get_current_trace_summary()
```

#### What data is stored when persisting traces?

The [`Trace`](./models.py#Trace) model stores trace ID, timing, request ID, user ID, and session ID. Each trace has related [`Span`](./models.py#Span) records with full OpenTelemetry span data (including SQL queries and attributes) and [`Log`](./models.py#Log) entries captured during the request.

## Installation

Install the `plain.observer` package from [PyPI](https://pypi.org/project/plain.observer/):

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
from plain.observer.urls import ObserverRouter
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        # ...
        include("observer/", ObserverRouter),
    ]
```

Run migrations to create the necessary database tables:

```bash
plain migrate
```

After installation, Observer will automatically integrate with your application's toolbar (if using `plain.toolbar`). You can access the web interface at `/observer/traces/` or use the CLI commands to analyze traces.

### Content Security Policy (CSP)

If you're using a Content Security Policy (CSP), the Observer toolbar panel requires `frame-ancestors 'self'` to display trace information in an iframe.

Without this directive, the toolbar panel will fail to load with a CSP error: `"Refused to frame... because an ancestor violates the following Content Security Policy directive: 'frame-ancestors 'none'"`.

Example CSP configuration:

```python
DEFAULT_RESPONSE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{request.csp_nonce}'; "
        "style-src 'self' 'nonce-{request.csp_nonce}'; "
        "frame-ancestors 'self'; "  # Required for Observer toolbar
        # ... other directives
    ),
}
```
