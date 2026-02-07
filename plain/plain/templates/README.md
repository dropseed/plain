# Templates

**Render HTML templates using Jinja2.**

- [Overview](#overview)
- [Template files](#template-files)
- [Template context](#template-context)
- [Built-in globals](#built-in-globals)
- [Built-in filters](#built-in-filters)
- [Custom globals and filters](#custom-globals-and-filters)
- [Custom template extensions](#custom-template-extensions)
- [Rendering templates manually](#rendering-templates-manually)
- [Custom Jinja environment](#custom-jinja-environment)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain uses Jinja2 for template rendering. You can refer to the [Jinja documentation](https://jinja.palletsprojects.com/en/stable/) for all of the features available.

Templates are typically used with `TemplateView` or one of its subclasses.

```python
# app/views.py
from plain.views import TemplateView


class ExampleView(TemplateView):
    template_name = "example.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["message"] = "Hello, world!"
        return context
```

```html
<!-- app/templates/example.html -->
{% extends "base.html" %}

{% block content %}
    <h1>{{ message }}</h1>
{% endblock %}
```

## Template files

Template files can live in two locations:

1. **`app/templates/`** - Your app's templates (highest priority)
2. **`{package}/templates/`** - Templates inside any installed package

All template directories are merged together, so you can override templates from installed packages by creating a file with the same name in `app/templates/`.

## Template context

When using `TemplateView`, you pass data to templates by overriding `get_template_context()`.

```python
class ProductView(TemplateView):
    template_name = "product.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["product"] = Product.objects.get(id=self.url_kwargs["id"])
        context["related_products"] = Product.objects.filter(category=context["product"].category)[:5]
        return context
```

The context is then available in your template:

```html
<h1>{{ product.name }}</h1>
<ul>
{% for item in related_products %}
    <li>{{ item.name }}</li>
{% endfor %}
</ul>
```

## Built-in globals

Plain provides several [global functions](./jinja/globals.py) available in all templates:

| Global                       | Description                        |
| ---------------------------- | ---------------------------------- |
| `asset(path)`                | Returns the URL for a static asset |
| `url(name, *args, **kwargs)` | Reverses a URL by name             |
| `Paginator`                  | The Paginator class for pagination |
| `now()`                      | Returns the current datetime       |
| `timedelta`                  | The timedelta class for date math  |
| `localtime(dt)`              | Converts a datetime to local time  |

```html
<link rel="stylesheet" href="{{ asset('css/style.css') }}">
<a href="{{ url('product_detail', id=product.id) }}">View</a>
<p>Generated at {{ now() }}</p>
```

## Built-in filters

Plain includes several [filters](./jinja/filters.py) for common operations:

| Filter                        | Description                          |
| ----------------------------- | ------------------------------------ |
| `strftime(format)`            | Formats a datetime                   |
| `strptime(format)`            | Parses a string to datetime          |
| `fromtimestamp(ts)`           | Creates datetime from timestamp      |
| `fromisoformat(s)`            | Creates datetime from ISO string     |
| `localtime(tz)`               | Converts to local timezone           |
| `timeuntil`                   | Human-readable time until a date     |
| `timesince`                   | Human-readable time since a date     |
| `json_script(id)`             | Outputs JSON safely in a script tag  |
| `islice(stop)`                | Slices iterables (useful for dicts)  |
| `pluralize(singular, plural)` | Returns plural suffix based on count |

```html
<p>Posted {{ post.created_at|timesince }} ago</p>
<p>{{ items|length }} item{{ items|length|pluralize }}</p>
<p>{{ 5 }} ox{{ 5|pluralize("en") }}</p>
{{ data|json_script("page-data") }}
```

## Custom globals and filters

You can register your own globals and filters in `app/templates.py` (or `{package}/templates.py`). These files are automatically imported when the template environment loads.

```python
# app/templates.py
from plain.templates import register_template_filter, register_template_global


@register_template_filter
def camel_case(value):
    """Convert a string to CamelCase."""
    return value.replace("_", " ").title().replace(" ", "")


@register_template_global
def app_version():
    """Return the current app version."""
    return "1.0.0"
```

Now you can use these in templates:

```html
<p>{{ "my_variable"|camel_case }}</p>  <!-- outputs: MyVariable -->
<footer>Version {{ app_version() }}</footer>
```

You can also register non-callable values as globals by providing a name:

```python
from plain.templates import register_template_global

register_template_global("1.0.0", name="APP_VERSION")
```

## Custom template extensions

For more complex template features, you can create Jinja extensions. The [`InclusionTagExtension`](./jinja/extensions.py#InclusionTagExtension) base class makes it easy to create custom tags that render their own templates.

```python
# app/templates.py
from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.runtime import settings


@register_template_extension
class AlertExtension(InclusionTagExtension):
    tags = {"alert"}
    template_name = "components/alert.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "message": args[0] if args else "",
            "type": kwargs.get("type", "info"),
        }
```

```html
<!-- app/templates/components/alert.html -->
<div class="alert alert-{{ type }}">{{ message }}</div>
```

```html
<!-- Usage in any template -->
{% alert "Something happened!" type="warning" %}
```

## Rendering templates manually

You can render templates outside of views using the [`Template`](./core.py#Template) class.

```python
from plain.templates import Template

html = Template("email/welcome.html").render({
    "user_name": "Alice",
    "activation_url": "https://example.com/activate/abc123",
})
```

If the template file doesn't exist, a [`TemplateFileMissing`](./core.py#TemplateFileMissing) exception is raised.

## Custom Jinja environment

By default, Plain uses a [`DefaultEnvironment`](./jinja/environments.py#DefaultEnvironment) that configures Jinja2 with sensible defaults:

- **Autoescaping** enabled for security
- **StrictUndefined** so undefined variables raise errors
- **Auto-reload** in debug mode
- **Loop controls** extension (`break`, `continue`)
- **Debug** extension

You can customize the environment by creating your own class and pointing to it in settings:

```python
# app/jinja.py
from plain.templates.jinja.environments import DefaultEnvironment


class CustomEnvironment(DefaultEnvironment):
    def __init__(self):
        super().__init__()
        # Add your customizations here
        self.globals["CUSTOM_SETTING"] = "value"
```

```python
# app/settings.py
TEMPLATES_JINJA_ENVIRONMENT = "app.jinja.CustomEnvironment"
```

## FAQs

#### Why am I getting "undefined variable" errors?

Plain uses Jinja's `StrictUndefined` mode, which raises an error when you reference a variable that doesn't exist in the context. This helps catch typos and missing data early. Make sure you're passing all required variables in `get_template_context()`.

#### Why does my template show an error about a callable?

Plain's template environment prevents accidentally rendering callables (functions, methods) directly. If you see an error like "X is callable, did you forget parentheses?", you probably need to add `()` to call the function:

```html
<!-- Wrong -->
{{ user.get_full_name }}

<!-- Correct -->
{{ user.get_full_name() }}
```

#### How do I use Jinja's loop controls?

Plain enables the `loopcontrols` extension by default, so you can use `break` and `continue` in loops:

```html
{% for item in items %}
    {% if item.skip %}
        {% continue %}
    {% endif %}
    {% if item.stop %}
        {% break %}
    {% endif %}
    <p>{{ item.name }}</p>
{% endfor %}
```

#### Where can I learn more about Jinja2?

The [Jinja2 documentation](https://jinja.palletsprojects.com/en/stable/) covers all the template syntax, including conditionals, loops, macros, and inheritance.

## Installation

The `plain.templates` module is included with Plain by default. No additional installation is required.
