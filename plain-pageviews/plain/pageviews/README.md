# plain-pageviews

Track pageviews from the client-side.

## Installation

Install `plain.pageviews` and add it to `INSTALLED_PACKAGES`.

Add `PageviewsRouter` to your urls.

Add `{% pageviews_js %}` to your `base.html` template to include the tracking code on the client side.

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

### Why not use server-side middleware?

Originally this was the idea. It turns out that tracking from the backend, while powerful, also means you have to identify all kinds of requests _not_ to track (assets, files, API calls, etc.). In the end, a simple client-side tracking script naturally accomplishes what we're looking for in a more straightforward way.
