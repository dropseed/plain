# plain.htmx

**Integrate HTMX with templates and views.**

- [Overview](#overview)
- [Template fragments](#template-fragments)
    - [Lazy template fragments](#lazy-template-fragments)
    - [How template fragments work](#how-template-fragments-work)
- [View actions](#view-actions)
- [Dedicated templates](#dedicated-templates)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can use `plain.htmx` to build HTMX-powered views that focus on server-side rendering without needing complicated URL structures or REST APIs.

The two main features are [template fragments](#template-fragments) and [view actions](#view-actions).

The [`HTMXView`](./views.py#HTMXView) class is the starting point for the server-side HTMX behavior. To use these features on a view, inherit from this class (yes, this is designed to work with class-based views).

```python
# app/views.py
from plain.htmx.views import HTMXView


class HomeView(HTMXView):
    template_name = "home.html"
```

In your `base.html` template (or wherever you need the HTMX scripts), you can use the `{% htmx_js %}` template tag:

```html
<!-- base.html -->
{% load htmx %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Site</title>
    {% htmx_js %}
</head>
<body>
    {% block content %}{% endblock %}
</body>
```

## Template fragments

An `{% htmxfragment %}` can render a specific part of your template in HTMX responses. When you use a fragment, all `hx-get`, `hx-post`, etc. elements inside that fragment will automatically send a request to the current URL, render _only_ the updated content for the fragment, and swap out the fragment.

Here's an example:

```html
<!-- home.html -->
{% extends "base.html" %}

{% load htmx %}

{% block content %}
<header>
  <h1>Page title</h1>
</header>

<main>
  {% htmxfragment "main" %}
  <p>The time is {% now "jS F Y H:i" %}</p>

  <button hx-get>Refresh</button>
  {% endhtmxfragment %}
</main>
{% endblock %}
```

Everything inside `{% htmxfragment %}` will automatically update when "Refresh" is clicked.

### Lazy template fragments

If you want to render a fragment lazily, you can add the `lazy` attribute to the `{% htmxfragment %}` tag.

```html
{% htmxfragment "main" lazy=True %}
<!-- This content will be fetched with hx-get -->
{% endhtmxfragment %}
```

This pairs nicely with passing a callable function or method as a context variable, which will only get invoked when the fragment actually gets rendered on the lazy load.

```python
def fetch_items():
    import time
    time.sleep(2)
    return ["foo", "bar", "baz"]


class HomeView(HTMXView):
    def get_template_context(self):
        context = super().get_template_context()
        context["items"] = fetch_items  # Missing () are on purpose!
        return context
```

```html
{% htmxfragment "main" lazy=True %}
<ul>
  {% for item in items %}
    <li>{{ item }}</li>
  {% endfor %}
</ul>
{% endhtmxfragment %}
```

### How template fragments work

When you use the `{% htmxfragment %}` tag, a standard `div` is output that looks like this:

```html
<div plain-hx-fragment="main" hx-swap="outerHTML" hx-target="this" hx-indicator="this">
  {{ fragment_content }}
</div>
```

The `plain-hx-fragment` is a custom attribute, but the rest are standard HTMX attributes.

When Plain renders the response to an HTMX request, it will get the `Plain-HX-Fragment` header, find the fragment with that name in the template, and render that for the response.

Then the response content is automatically swapped in to replace the content of your `{% htmxfragment %}` tag.

Note that there is no URL specified on the `hx-get` attribute. By default, HTMX will send the request to the current URL for the page. When you're working with fragments, this is typically the behavior you want! (You're on a page and want to selectively re-render a part of that page.)

The `{% htmxfragment %}` tag is somewhat similar to a `{% block %}` tag -- the fragments on a page should be named and unique, and you can't use it inside of loops. For fragment-like behavior inside of a for-loop, you'll most likely want to set up a dedicated URL that can handle a single instance of the looped items, and maybe leverage [dedicated templates](#dedicated-templates).

## View actions

View actions let you define multiple "actions" on a class-based view. This is an alternative to defining specific API endpoints or form views to handle basic button interactions.

With view actions you can design a single view that renders a single template, and associate buttons in that template with class methods in the view.

As an example, let's say we have a `PullRequest` model and we want users to be able to open, close, or merge it with a button.

In your template, use the `plain-hx-action` attribute to name the action:

```html
{% extends "base.html" %}

{% load htmx %}

{% block content %}
<header>
  <h1>{{ pullrequest }}</h1>
</header>

<main>
  {% htmxfragment "pullrequest" %}
  <p>State: {{ pullrequest.state }}</p>

  {% if pullrequest.state == "open" %}
    <!-- If it's open, they can close or merge it -->
    <button hx-post plain-hx-action="close">Close</button>
    <button hx-post plain-hx-action="merge">Merge</button>
  {% else if pullrequest.state == "closed" %}
    <!-- If it's closed, it can be re-opened -->
    <button hx-post plain-hx-action="open">Open</button>
  {% endif %}

  {% endhtmxfragment %}
</main>
{% endblock %}
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
    def htmx_post_open(self):
        if self.object.state != "closed":
            raise ValueError("Only a closed pull request can be opened")

        self.object.state = "closed"
        self.object.save()

        # Render the updated content with the standard calls
        # (which will selectively render the fragment if applicable)
        return self.render_template()

    def htmx_post_close(self):
        if self.object.state != "open":
            raise ValueError("Only an open pull request can be closed")

        self.object.state = "open"
        self.object.save()

        return self.render_template()

    def htmx_post_merge(self):
        if self.object.state != "open":
            raise ValueError("Only an open pull request can be merged")

        self.object.state = "merged"
        self.object.save()

        return self.render_template()
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

Because template fragments don't work inside of loops, for example, you'll often need to define dedicated URLs to handle the HTMX behaviors for individual items in a loop. You can sometimes think of these as "pages within a page".

So if you have a template that renders a collection of items, you can do the initial render using a `{% include %}`:

```html
<!-- pullrequests/pullrequest_list.html -->
{% extends "base.html" %}

{% block content %}

{% for pullrequest in pullrequests %}
<div>
  {% include "pullrequests/pullrequest_detail_htmx.html" %}
</div>
{% endfor %}

{% endblock %}
```

And then subsequent HTMX requests/actions on individual items can be handled by a separate URL/View:

```html
<!-- pullrequests/pullrequest_detail_htmx.html -->
<div hx-url="{% url 'pullrequests:detail' pullrequest.uuid %}" hx-swap="outerHTML" hx-target="this">
  <!-- Send all HTMX requests to a URL for single pull requests (works inside of a loop, or on a single detail page) -->
  <h2>{{ pullrequest.title }}</h2>
  <button hx-get>Refresh</button>
  <button hx-post plain-hx-action="update">Update</button>
</div>
```

_If_ you need a URL to render an individual item, you can simply include the same template fragment in most cases:

```html
<!-- pullrequests/pullrequest_detail.html -->
{% extends "base.html" %}

{% block content %}

{% include "pullrequests/pullrequest_detail_htmx.html" %}

{% endblock %}
```

```python
# urls.py and views.py
# urls.py
default_namespace = "pullrequests"

urlpatterns = [
  path("<uuid:uuid>/", views.PullRequestDetailView, name="detail"),
]

# views.py
class PullRequestDetailView(HTMXView, DetailView):
  def htmx_post_update(self):
      self.object.update()

      return self.render_template()
```

## FAQs

#### How do I add a Tailwind CSS variant for loading states?

The standard behavior for `{% htmxfragment %}` is to set `hx-indicator="this"` on the rendered element. This tells HTMX to add the `htmx-request` class to the fragment element when it is loading.

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

Add the HTMX JavaScript to your base template:

```html
<!-- base.html -->
{% load htmx %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>My Site</title>
    {% htmx_js %}
</head>
<body>
    {% block content %}{% endblock %}
</body>
```

Create a view that inherits from `HTMXView`:

```python
# app/views.py
from plain.htmx.views import HTMXView


class HomeView(HTMXView):
    template_name = "home.html"
```

Create a template with an HTMX fragment:

```html
<!-- home.html -->
{% extends "base.html" %}
{% load htmx %}

{% block content %}
{% htmxfragment "content" %}
<p>The time is {% now "jS F Y H:i" %}</p>
<button hx-get>Refresh</button>
{% endhtmxfragment %}
{% endblock %}
```
