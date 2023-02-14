# forge-htmx

The `forge-htmx` Django package adds a couple of unique features for working with HTMX.
One is [template fragments](#template-fragments) and the other is [view actions](#view-actions).

The combination of these features lets you build HTMX-powered views that focus on server-side rendering and avoid overly complicated URL structures or REST APIs that you may not otherwise need.

The `HTMXViewMixin` is the starting point for the server-side HTMX behavior.
To use these feaures on a view,
simply inherit from the class (yes, this is designed to work with class-based views).

```python
from django.views.generic import TemplateView

from forgehtmx.views import HTMXViewMixin


class HomeView(HTMXViewMixin, TemplateView):
    template_name = "home.html"
```

In your `base.html` template (or wherever need the HTMX scripts),
you can use the `{% htmx_js %}` template tag:

```html
<!-- base.template.html -->
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

## Installation

You can install `forge-htmx` with any Django project:

```sh
pip install forge-htmx
```

Then add `forgehtmx` to `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    "forgehtmx",
]
```

## Template Fragments

An `{% htmxfragment %}` can be used to render a specific part of your template in HTMX responses.
When you use a fragment, all `hx-get`, `hx-post`, etc. elements inside that fragment will automatically send a request to the current URL,
render *only* the updated content for the fragment,
and swap out the fragment.

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
  {% htmxfragment main %}
  <p>The time is {% now "jS F Y H:i" %}</p>

  <button hx-get>Refresh</button>
  {% endhtmxfragment %}
</main>
{% endblock %}
```

Everything inside `{% htmxfragment %}` will automatically update when "Refresh" is clicked.

### Lazy template fragments

If you want to render a fragment lazily,
you can add the `lazy` attribute to the `{% htmxfragment %}` tag.

```html
{% htmxfragment main lazy %}
<!-- This content will be fetched with hx-get -->
{% endhtmxfragment %}
```

This pairs nicely with passing a callable function or method as a context variable,
which will only get invoked when the fragment actually gets rendered on the lazy load.

```python
def fetch_items():
    import time
    time.sleep(2)
    return ["foo", "bar", "baz"]


class HomeView(HTMXViewMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["items"] = fetch_items  # Missing () are on purpose!
        return context
```

```html
{% htmxfragment main lazy %}
<ul>
  {% for item in items %}
    <li>{{ item }}</li>
  {% endfor %}
</ul>
{% endhtmxfragment %}
```

### How does it work?

When you use the `{% htmxfragment %}` tag,
a standard `div` is output that looks like this:

```html
<div fhx-fragment="main" hx-swap="outerHTML" hx-target="this" hx-indicator="this">
  {{ fragment_content }}
</div>
```

The `fhx-fragment` is a custom attribute that we've added ("F" is for "Forge"),
but the rest are standard HTMX attributes.

When Django renders the response to an HTMX request,
it will get the `FHX-Fragment` header,
find the fragment with that name in the template,
and render that for the response.

Then the response content is automatically swapped in to replace the content of your `{% htmxfragment %}` tag.

Note that there is no URL specified on the `hx-get` attribute.
By default, HTMX will send the request to the current URL for the page.
When you're working with fragments, this is typically the behavior you want!
(You're on a page and want to selectively re-render a part of that page.)

The `{% htmxfragment %}` tag is somewhat similar to a `{% block %}` tag --
the fragments on a page should be named and unique,
and you can't use it inside of loops.
For fragment-like behavior inside of a for-loop,
you'll most likely want to set up a dedicated URL that can handle a single instance of the looped items,
and maybe leverage [dedicated templates](#dedicated-templates).

## View Actions

View actions let you define multiple "actions" on a class-based view.
This is an alternative to defining specific API endpoints or form views to handle basic button interactions.

With view actions you can design a single view that renders a single template,
and associate buttons in that template with class methods in the view.

As an example, let's say we have a `PullRequest` model and we want users to be able to open, close, or merge it with a button.

In our template, we would use the `fhx-action` attribute to name the action:

```html
{% extends "base.html" %}

{% load htmx %}

{% block content %}
<header>
  <h1>{{ pullrequest }}</h1>
</header>

<main>
  {% htmxfragment pullrequest %}
  <p>State: {{ pullrequest.state }}</p>

  {% if pullrequest.state == "open" %}
    <!-- If it's open, they can close or merge it -->
    <button hx-post fhx-action="close">Close</button>
    <button hx-post fhx-action="merge">Merge</button>
  {% else if pullrequest.state == "closed" %}
    <!-- If it's closed, it can be re-opened -->
    <button hx-post fhx-action="open">Open</button>
  {% endif %}

  {% endhtmxfragment %}
</main>
{% endblock %}
```

Then in the view class, we can define methods for each HTTP method + `fhx-action`:

```python
class PullRequestDetailView(HTMXViewMixin, DetailView):
    def get_queryset(self):
        # The queryset will apply to all actions on the view, so "permission" logic can be shared
        return super().get_queryset().filter(users=self.request.user)

    # Action handling methods follow this format:
    # htmx_{method}_{action}
    def htmx_post_open(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self.object.state != "closed":
            raise ValueError("Only a closed pull request can be opened")

        self.object.state = "closed"
        self.object.save()

        # Render the updated content the standard calls
        # (which will selectively render our fragment if applicable)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def htmx_post_close(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self.object.state != "open":
            raise ValueError("Only a open pull request can be closed")

        self.object.state = "open"
        self.object.save()

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def htmx_post_merge(self, request, *args, **kwargs):
        self.object = self.get_object()

        if self.object.state != "open":
            raise ValueError("Only a open pull request can be merged")

        self.object.state = "merged"
        self.object.save()

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)
```

This can be a matter of preference,
but typically you may end up building out an entire form, API, or set of URLs to handle these behaviors.
If you application is only going to handle these actions via HTMX,
then a single View may be a simpler way to do it.

Note that currently we don't have many helper-functions for parsing or returning HTMX responses --
this can basically all be done through standard request and response headers:

```python
class PullRequestDetailView(HTMXViewMixin, DetailView):
    def get_queryset(self):
        # The queryset will apply to all actions on the view, so "permission" logic can be shared
        return super().get_queryset().filter(users=self.request.user)

    # You can also leave off the "fhx-action" attribute and just handle the HTTP method
    def htmx_delete(self, request, *args, **kwargs):
        self.object = self.get_object()

        self.object.delete()

        # Tell HTMX to do a client-side redirect when it receives the response
        response = HttpResponse(status=204)
        response["HX-Redirect"] = "/"
        return response
```

## Dedicated Templates

A small additional features of `forge-htmx` is that it will automatically find templates named `{template_name}_htmx.html` for HTMX requests.
More than anything, this is just a nice way to formalize a naming scheme for template "partials" dedicated to HTMX.

Because template fragments don't work inside of loops,
for example,
you'll often need to define dedicated URLs to handle the HTMX behaviors for individual items in a loop.
You can sometimes think of these as "pages within a page".

So if you have a template that renders a collection of items,
you can do the initial render using a Django `{% include %}`:

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
  <button hx-post fhx-action="update">Update</button>
</div>
```

*If* you need a URL to render an individual item, you can simply include the same template fragment in most cases:

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
app_name = "pullrequests"

urlpatterns = [
  path("<uuid:uuid>/", views.PullRequestDetailView.as_view(), name="detail"),
]

# views.py
class PullRequestDetailView(HTMXViewMixin, DetailView):
  def htmx_post_update(self, request, *args, **kwargs):
      self.object = self.get_object()

      self.object.update()

      context = self.get_context_data(object=self.object)
      return self.render_to_response(context)
```

## Tailwind CSS variant

The standard behavior for `{% htmxfragment %}` is to set `hx-indicator="this"` on the rendered element.
This tells HTMX to add the `htmx-request` class to the fragment element when it is loading.

Since Forge emphasizes using Tailwind CSS,
here's a simple variant you can add to your `tailwind.config.js` to easily style the loading state:

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

## CSRF tokens

We configure CSRF tokens for you with the HTMX JS API.
You don't have to put `hx-headers` on the `<body>` tag, for example.

## Error classes

This app also includes an HTMX extension for adding error classes for failed requests.

- `htmx-error-response` for `htmx:responseError`
- `htmx-error-response-{{ status_code }}` for `htmx:responseError`
- `htmx-error-send` for `htmx:sendError`

To enable them, use `hx-ext="error-classes"`.

You can add the ones you want as Tailwind variants and use them to show error messages.

```js
const plugin = require('tailwindcss/plugin')

module.exports = {
  plugins: [
    // Add variants for htmx-request class for loading states
    plugin(({addVariant}) => addVariant('htmx-error-response-429', ['&.htmx-error-response-429', '.htmx-error-response-429 &']))
  ],
}
```
