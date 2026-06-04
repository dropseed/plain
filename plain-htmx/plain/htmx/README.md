# plain.htmx

**Integrate HTMX with templates and views.**

- [Overview](#overview)
- [Fragment wrappers](#fragment-wrappers)
- [View actions](#view-actions)
- [Dedicated templates](#dedicated-templates)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use `plain.htmx` to build HTMX-powered views that focus on server-side rendering without needing complicated URL structures or REST APIs.

The two main features are [view actions](#view-actions) and [dedicated templates](#dedicated-templates).

The [`HTMXView`](./views.py#HTMXView) class is the starting point for the server-side HTMX behavior. To use these features on a view, inherit from this class (yes, this is designed to work with class-based views).

```python
# app/views.py
from plain.htmx.views import HTMXView


class HomeView(HTMXView):
    template_name = "home.html"
```

In your `base.html` template (or wherever you need the HTMX scripts), import the `htmx_js` helper in frontmatter and call it where you want the `<script>` tags:

```html
<!-- base.html -->
---
imports:
  - from plain.htmx.html import htmx_js
attrs:
  request: plain.http.Request
slots:
  default: required
---
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Site</title>
    {{ htmx_js(request) }}
</head>
<body>
    {{ children }}
</body>
</html>
```

## Fragment wrappers

A fragment wrapper is a `<div>` that carries a `plain-hx-fragment` name plus the standard HTMX swap/target attributes. Any `hx-get`/`hx-post` element inside it sends its request to the current URL and targets the wrapper for the swap. The cleanest way to reuse that markup is a small component:

```html
<!-- components/HtmxFragment.html -->
---
attrs:
  name: str
slots:
  default: required
---
<div
    plain-hx-fragment="{{ name }}"
    hx-swap="innerHTML"
    hx-target="this"
    hx-indicator="this"
    id="{{ "plain-hx-fragment-" + name }}"
>{{ children }}</div>
```

Use it to wrap the part of a page you want to re-render:

```html
<!-- detail.html -->
---
components:
  - base as Base
  - components/HtmxFragment
attrs:
  pullrequest: Any
---
<Base>
    <HtmxFragment name="pullrequest">
        <p>State: {{ pullrequest.state }}</p>
        <button hx-post plain-hx-action="merge">Merge</button>
    </HtmxFragment>
</Base>
```

There is no URL on the `hx-post` attribute — by default HTMX sends the request to the current URL for the page, which is what you want when re-rendering part of the current page. The view handles the action (see [View actions](#view-actions) below) and returns markup that HTMX swaps into the wrapper.

> **Note:** the old Jinja `{% htmxfragment %}` tag — which extracted and returned _only_ the named fragment's subtree server-side — is not available in `plain.html`. Today an `HTMXView` action re-renders and returns the whole template. To swap just a region, give that region its own URL/template (see [Dedicated templates](#dedicated-templates)) so the response is scoped to the part you want, and point `hx-target` at the wrapper.

## View actions

View actions let you define multiple "actions" on a class-based view. This is an alternative to defining specific API endpoints or form views to handle basic button interactions.

With view actions you can design a single view that renders a single template, and associate buttons in that template with class methods in the view.

As an example, let's say we have a `PullRequest` model and we want users to be able to open, close, or merge it with a button.

In your template, use the `plain-hx-action` attribute to name the action:

```html
---
components:
  - base as Base
  - components/HtmxFragment
attrs:
  pullrequest: Any
---
<Base>
    <header>
        <h1>{{ pullrequest }}</h1>
    </header>

    <main>
        <HtmxFragment name="pullrequest">
            <p>State: {{ pullrequest.state }}</p>

            {% if pullrequest.state == "open" %}
                {# If it's open, they can close or merge it #}
                <button hx-post plain-hx-action="close">Close</button>
                <button hx-post plain-hx-action="merge">Merge</button>
            {% elif pullrequest.state == "closed" %}
                {# If it's closed, it can be re-opened #}
                <button hx-post plain-hx-action="open">Open</button>
            {% endif %}
        </HtmxFragment>
    </main>
</Base>
```

Then in the view class, define methods for each HTTP method + `plain-hx-action`:

```python
from plain.htmx.views import HTMXView
from plain.views import DetailView


class PullRequestDetailView(HTMXView, DetailView):
    def get_queryset(self):
        # The queryset will apply to all actions on the view, so "permission" logic can be shared
        return super().get_queryset().filter(users=self.user)

    # Action handling methods follow this format:
    # htmx_{method}_{action}
    #
    # Return `None` to re-render the current template (or active fragment).
    # Return a `Response` only when you need to do something else —
    # a redirect, a 204, a custom payload.
    def htmx_post_open(self):
        if self.object.state != "closed":
            raise ValueError("Only a closed pull request can be opened")

        self.object.state = "closed"
        self.object.update()

    def htmx_post_close(self):
        if self.object.state != "open":
            raise ValueError("Only an open pull request can be closed")

        self.object.state = "open"
        self.object.update()

    def htmx_post_merge(self):
        if self.object.state != "open":
            raise ValueError("Only an open pull request can be merged")

        self.object.state = "merged"
        self.object.update()
```

This can be a matter of preference, but typically you may end up building out an entire form, API, or set of URLs to handle these behaviors. If your application is only going to handle these actions via HTMX, then a single View may be a simpler way to do it.

You can also handle HTMX requests without a specific action by just implementing the HTTP method:

```python
from plain.http import HttpResponse


class PullRequestDetailView(HTMXView, DetailView):
    def get_queryset(self):
        return super().get_queryset().filter(users=self.user)

    # You can also leave off the "plain-hx-action" attribute and just handle the HTTP method
    def htmx_delete(self):
        self.object.delete()

        # Tell HTMX to do a client-side redirect when it receives the response
        response = HttpResponse(status_code=204)
        response.headers["HX-Redirect"] = "/"
        return response
```

## Dedicated templates

A small additional feature is that `plain.htmx` will automatically find templates named `{template_name}_htmx.html` for HTMX requests. More than anything, this is just a nice way to formalize a naming scheme for template "partials" dedicated to HTMX.

For cases where loop items need their own URL (e.g., each item has a detail page), you can define dedicated URLs to handle the HTMX behaviors for individual items. You can sometimes think of these as "pages within a page".

Extract the per-item markup into a component so the list and the dedicated detail template both render the same thing. The component points its HTMX requests at the item's own URL:

```html
<!-- components/PullRequestItem.html -->
---
imports:
  - from plain.urls import reverse as url
attrs:
  pullrequest: Any
---
<div
    hx-get="{{ url('pullrequests:detail', uuid=pullrequest.uuid) }}"
    hx-swap="outerHTML"
    hx-target="this"
>
    {# Send all HTMX requests to a URL for single pull requests
       (works inside of a loop, or on a single detail page) #}
    <h2>{{ pullrequest.title }}</h2>
    <button hx-get>Refresh</button>
    <button hx-post plain-hx-action="update">Update</button>
</div>
```

The list template renders the component for each item:

```html
<!-- pullrequests/pullrequest_list.html -->
---
components:
  - base as Base
  - components/PullRequestItem
attrs:
  pullrequests: Any
---
<Base>
    {% for pullrequest in pullrequests %}
        <div>
            <PullRequestItem pullrequest="{{ pullrequest }}" />
        </div>
    {% endfor %}
</Base>
```

_If_ you need a URL to render an individual item, render the same component on its own:

```html
<!-- pullrequests/pullrequest_detail.html -->
---
components:
  - base as Base
  - components/PullRequestItem
attrs:
  pullrequest: Any
---
<Base>
    <PullRequestItem pullrequest="{{ pullrequest }}" />
</Base>
```

```python
# urls.py
from plain.urls import Router, path

from . import views


class PullRequestsRouter(Router):
    namespace = "pullrequests"
    urls = [
        path("<uuid:uuid>/", views.PullRequestDetailView, name="detail"),
    ]


# views.py
class PullRequestDetailView(HTMXView, DetailView):
    def htmx_post_update(self):
        self.object.update()
```

## FAQs

#### How do I add a Tailwind CSS variant for loading states?

The `HtmxFragment` component sets `hx-indicator="this"` on the rendered element. This tells HTMX to add the `htmx-request` class to the fragment element when it is loading.

Here's a simple variant you can add to your `tailwind.config.js` to easily style the loading state:

```js
const plugin = require('tailwindcss/plugin')

module.exports = {
  plugins: [
    // Add variants for htmx-request class for loading states
    plugin(({addVariant}) => addVariant('htmx-request', ['&.htmx-request', '.htmx-request &']))
  ],
}
```

You can then prefix any class with `htmx-request:` to decide what it looks like while HTMX requests are being sent:

```html
<!-- The "htmx-request" class will be added to the <form> by default -->
<form hx-post="{{ url }}">
    <!-- Showing an element -->
    <div class="hidden htmx-request:block">
        Loading
    </div>

    <!-- Changing a button's class -->
    <button class="text-white bg-black htmx-request:opacity-50 htmx-request:cursor-wait" type="submit">Submit</button>
</form>
```

#### How are CSRF tokens handled?

CSRF tokens are configured automatically with the HTMX JS API. You don't have to put `hx-headers` on the `<body>` tag.

#### How do I show error states?

This package includes an HTMX extension for adding error classes for failed requests:

- `htmx-error-response` for `htmx:responseError`
- `htmx-error-response-{{ status_code }}` for `htmx:responseError`
- `htmx-error-send` for `htmx:sendError`

To enable them, use `hx-ext="plain-errors"`.

You can add the ones you want as Tailwind variants and use them to show error messages:

```js
const plugin = require('tailwindcss/plugin')

module.exports = {
  plugins: [
    // Add variants for htmx-request class for loading states
    plugin(({addVariant}) => addVariant('htmx-error-response-429', ['&.htmx-error-response-429', '.htmx-error-response-429 &']))
  ],
}
```

#### How do I configure HTMX for CSP?

If you're using Content Security Policy, you can disable the indicator styles that HTMX adds inline:

```html
<meta name="htmx-config" content='{"includeIndicatorStyles":false}'>
```

## Installation

Install the `plain.htmx` package from [PyPI](https://pypi.org/project/plain.htmx/):

```bash
uv add plain.htmx
```

Add `plain.htmx` to your installed packages:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.htmx",
]
```

Add the HTMX JavaScript to your base template by importing the `htmx_js` helper in frontmatter and calling it in the `<head>`:

```html
<!-- base.html -->
---
imports:
  - from plain.htmx.html import htmx_js
attrs:
  request: plain.http.Request
slots:
  default: required
---
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Site</title>
    {{ htmx_js(request) }}
</head>
<body>
    {{ children }}
</body>
</html>
```

Create a view that inherits from `HTMXView`:

```python
# app/views.py
from plain.htmx.views import HTMXView


class HomeView(HTMXView):
    template_name = "home.html"
```

Create a template with an HTMX fragment, using the `HtmxFragment` component (see [Fragment wrappers](#fragment-wrappers)):

```html
<!-- home.html -->
---
imports:
  - from datetime import datetime
components:
  - base as Base
  - components/HtmxFragment
---
<Base>
    <HtmxFragment name="content">
        <p>The time is {{ datetime.now().strftime("%-d %B %Y %H:%M") }}</p>
        <button hx-get>Refresh</button>
    </HtmxFragment>
</Base>
```
