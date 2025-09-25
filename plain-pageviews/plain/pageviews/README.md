# plain.pageviews

**Track pageviews from both client-side and server-side.**

- [Overview](#overview)
- [Server-side tracking](#server-side-tracking)
- [Attribution tracking](#attribution-tracking)
- [Admin integration](#admin-integration)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Add `PageviewsRouter` to your urls.

Add `{% pageviews_js %}` to your `base.html` template to include the tracking code on the client side.

## Server-side tracking

You can also track pageviews directly from your server-side code using the [`Pageview.create_from_request()`](./models.py#create_from_request) method:

```python
from plain.pageviews.models import Pageview

def my_view(request):
    # Track this pageview on the server
    Pageview.create_from_request(request, title="My Page Title")

    # Your view logic here
    return render(request, "my_template.html")
```

The `title` parameter is optional. If not provided, the pageview will be created without a title.

Server-side tracking differs from client-side tracking in that:

- The timestamp is generated on the server (not the client)
- The referrer is extracted from the request headers (`HTTP_REFERER`)
- The URL uses the request's full path
- Impersonation is automatically detected and ignored

## Attribution tracking

Pageviews automatically tracks traffic sources and campaigns from URL parameters. Three fields are captured:

- **Source**: Where the traffic came from
- **Medium**: How the traffic arrived
- **Campaign**: Which campaign generated the traffic

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

- `?gclid=...` → source="google", medium="cpc" (Google Ads)
- `?fbclid=...` → source="facebook", medium="social" (Facebook/Meta)
- `?msclkid=...` → source="bing", medium="cpc" (Microsoft/Bing Ads)
- `?ttclid=...` → source="tiktok", medium="cpc" (TikTok Ads)
- `?twclid=...` → source="twitter", medium="cpc" (Twitter/X Ads)

### Priority order

Parameters are processed in this order:

1. `utm_source` takes priority over `ref`
2. Auto-detected tracking IDs (gclid, fbclid, etc.)
3. All values are normalized to lowercase

### Server-side extraction

Attribution parameters are automatically extracted server-side from the URL when using either tracking method. No client-side changes are needed.

## Admin integration

```python
from plain.pageviews.admin import UserPageviewsCard


@register_viewset
class UserAdmin(AdminViewset):
    class DetailView(AdminModelDetailView):
        model = User
        cards = [UserPageviewsCard]
```

## FAQs

#### When should I use server-side vs client-side tracking?

**Client-side tracking** (via `{% pageviews_js %}`) is great for:

- Standard web pages viewed by users
- Getting accurate client-side information (full URL, page title, client timestamp)
- Automatically tracking without adding code to every view

**Server-side tracking** (via `Pageview.create_from_request()`) is useful for:

- Tracking specific user actions or events
- When you need guaranteed tracking (not blocked by ad blockers or disabled JavaScript)
- API endpoints or non-HTML responses
- Custom tracking logic based on business rules

#### Why not use server-side middleware for automatic tracking?

Originally this was considered. However, tracking from the backend with middleware means you have to identify all kinds of requests _not_ to track (assets, files, API calls, etc.). Client-side tracking naturally accomplishes what we're looking for in a more straightforward way, while server-side methods give you control when you need it.

## Installation

Install the `plain.pageviews` package from [PyPI](https://pypi.org/project/plain.pageviews/):

```bash
uv add plain.pageviews
```

Add to your `INSTALLED_PACKAGES`:

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.pageviews",
]
```
