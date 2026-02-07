# plain.pageviews

**Track pageviews from both client-side and server-side.**

- [Overview](#overview)
- [Client-side tracking](#client-side-tracking)
- [Server-side tracking](#server-side-tracking)
- [Attribution tracking](#attribution-tracking)
    - [Supported parameters](#supported-parameters)
    - [Priority order](#priority-order)
- [Admin integration](#admin-integration)
- [Data retention](#data-retention)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can track pageviews in two ways: client-side using JavaScript, or server-side directly from your views. Both methods store data in the same `Pageview` model and automatically extract attribution parameters from URLs.

```python
from plain.pageviews.models import Pageview

# Server-side tracking example
def my_view(request):
    Pageview.create_from_request(request, title="Product Page")
    return TemplateResponse(request, "product.html")
```

For most use cases, client-side tracking is the simplest approach. Add the router to your URLs and include the JavaScript tag in your base template.

## Client-side tracking

Client-side tracking uses a small JavaScript snippet that sends pageview data via the Beacon API. This captures the full browser URL, page title, referrer, and timestamp.

Add `{% pageviews_js %}` to your base template:

```html
<!DOCTYPE html>
<html>
<head>
    <title>My App</title>
</head>
<body>
    {% block content %}{% endblock %}
    {% pageviews_js %}
</body>
</html>
```

The JavaScript runs asynchronously and sends a POST request to the tracking endpoint with:

- `url`: The full browser URL (including query parameters)
- `title`: The document title
- `referrer`: The referring page URL
- `timestamp`: Client-side timestamp in ISO 8601 format

## Server-side tracking

You can track pageviews directly from your views using [`Pageview.create_from_request()`](./models.py#create_from_request):

```python
from plain.pageviews.models import Pageview

def checkout_view(request):
    Pageview.create_from_request(request, title="Checkout")
    # Your view logic here
    return TemplateResponse(request, "checkout.html")
```

Server-side tracking differs from client-side tracking:

- The timestamp is generated on the server, not the client
- The referrer is extracted from the `Referer` request header
- The URL uses the request's full path via `request.build_absolute_uri()`
- Impersonation sessions are automatically ignored (no pageview is created)

All parameters are optional. You can override any value:

```python
Pageview.create_from_request(
    request,
    url="https://example.com/custom-path",
    title="Custom Title",
    source="partner",
    medium="referral",
    campaign="summer_promo",
)
```

## Attribution tracking

Pageviews automatically tracks traffic sources and campaigns from URL parameters. Three fields are captured:

- **Source**: Where the traffic came from (e.g., "google", "newsletter")
- **Medium**: How the traffic arrived (e.g., "cpc", "email", "social")
- **Campaign**: Which campaign generated the traffic (e.g., "summer_sale")

### Supported parameters

**UTM parameters** (standard marketing tracking):

```
?utm_source=newsletter&utm_medium=email&utm_campaign=welcome_series
```

**Simple ref parameter** (developer-friendly alternative):

```
?ref=newsletter
```

**Auto-detected tracking IDs** (no configuration needed):

| Parameter | Source   | Medium |
| --------- | -------- | ------ |
| `gclid`   | google   | cpc    |
| `fbclid`  | facebook | social |
| `msclkid` | bing     | cpc    |
| `ttclid`  | tiktok   | cpc    |
| `twclid`  | twitter  | cpc    |

### Priority order

Parameters are processed in this order:

1. `utm_source` takes priority over `ref`
2. Auto-detected tracking IDs (gclid, fbclid, etc.) fill in values if UTM parameters are not present
3. All values are normalized to lowercase

Attribution parameters are automatically extracted from the URL in both client-side and server-side tracking. The extraction happens server-side via [`extract_tracking_params()`](./params.py#extract_tracking_params).

## Admin integration

The package includes a built-in admin viewset that shows all pageviews with filtering and search.

You can also add a pageviews card to your user admin detail view:

```python
from plain.admin.views import AdminModelDetailView, AdminViewset, register_viewset
from plain.pageviews.admin import UserPageviewsCard

@register_viewset
class UserAdmin(AdminViewset):
    class DetailView(AdminModelDetailView):
        model = User
        cards = [UserPageviewsCard]
```

The [`UserPageviewsCard`](./admin.py#UserPageviewsCard) displays the 50 most recent pageviews for that user.

For dashboard-level analytics, you can use [`PageviewsTrendCard`](./admin.py#PageviewsTrendCard) which shows pageview counts over time.

## Data retention

The package includes a chore that automatically cleans up old pageviews. The [`ClearOldPageviews`](./chores.py#ClearOldPageviews) chore runs according to your chores schedule and deletes:

- Anonymous pageviews older than 90 days (configurable)
- Authenticated pageviews older than 365 days (configurable)

## Settings

| Setting                                       | Default               | Env var                                        |
| --------------------------------------------- | --------------------- | ---------------------------------------------- |
| `PAGEVIEWS_ASSOCIATE_ANONYMOUS_SESSIONS`      | `True`                | `PLAIN_PAGEVIEWS_ASSOCIATE_ANONYMOUS_SESSIONS` |
| `PAGEVIEWS_ANONYMOUS_RETENTION_TIMEDELTA`     | `timedelta(days=90)`  | -                                              |
| `PAGEVIEWS_AUTHENTICATED_RETENTION_TIMEDELTA` | `timedelta(days=365)` | -                                              |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### When should I use server-side vs client-side tracking?

**Client-side tracking** (via `{% pageviews_js %}`) works best for:

- Standard web pages viewed by users
- Getting accurate client-side information (full URL with hash fragments, page title)
- Automatically tracking without adding code to every view

**Server-side tracking** (via `Pageview.create_from_request()`) works best for:

- Tracking specific user actions or events
- Guaranteed tracking that cannot be blocked by ad blockers or disabled JavaScript
- API endpoints or non-HTML responses
- Custom tracking logic based on business rules

#### Why not use server-side middleware for automatic tracking?

Tracking from the backend with middleware means you have to identify all kinds of requests _not_ to track (assets, files, API calls, etc.). Client-side tracking naturally captures what you want in a more straightforward way, while server-side methods give you control when you need it.

#### How does anonymous session association work?

When `PAGEVIEWS_ASSOCIATE_ANONYMOUS_SESSIONS` is enabled (the default), pageviews from anonymous users are tracked with a session ID. When that user later logs in, all their previous anonymous pageviews are automatically associated with their user account. This gives you a complete picture of the user's journey before they registered or logged in.

#### What happens during impersonation?

When an admin is impersonating a user, pageviews are not tracked. This prevents admin activity from polluting the user's pageview history.

## Installation

Install the package from PyPI:

```bash
uv add plain.pageviews
```

Add `plain.pageviews` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.pageviews",
]
```

Run migrations to create the database table:

```bash
plain models migrate
```

Add the router to your URLs:

```python
# app/urls.py
from plain.urls import Router, include, path
from plain.pageviews.urls import PageviewsRouter

class AppRouter(Router):
    namespace = ""
    urls = [
        # Your other URLs...
        include("pageviews/", PageviewsRouter),
    ]
```

For client-side tracking, add the JavaScript tag to your base template:

```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}My App{% endblock %}</title>
</head>
<body>
    {% block content %}{% endblock %}
    {% pageviews_js %}
</body>
</html>
```

You can now track pageviews automatically via JavaScript, or manually from your views using `Pageview.create_from_request(request)`.
