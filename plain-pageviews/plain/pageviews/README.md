# plain.pageviews

**Track pageviews from the client-side.**

- [Admin integration](#admin-integration)
- [FAQs](#faqs)
- [Installation](#installation)

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

#### Why not use server-side middleware?

Originally this was the idea. It turns out that tracking from the backend, while powerful, also means you have to identify all kinds of requests _not_ to track (assets, files, API calls, etc.). In the end, a simple client-side tracking script naturally accomplishes what we're looking for in a more straightforward way.

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
