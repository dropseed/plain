# Templates

**Render HTML templates using Jinja.**

Plain uses Jinja2 for template rendering. You can refer to the [Jinja documentation](https://jinja.palletsprojects.com/en/stable/api/) for all of the features available.

In general, templates are used in combination with `TemplateView` or a more specific subclass of it.

```python
from plain.views import TemplateView


class ExampleView(TemplateView):
    template_name = "example.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["message"] = "Hello, world!"
        return context
```

```html
<!-- example.html -->
{% extends "base.html" %}

{% block content %}
    <h1>{{ message }}</h1>
{% endblock %}
```

## Template files

Template files can be located in either a root `app/templates`,
or the `<pkg>/templates` directory of any installed package.

All template directories are "merged" together, allowing you to override templates from other packages. The `app/templates` will take priority, followed by `INSTALLED_PACKAGES` in the order they are defined.

## Extending Jinja

Plain includes a set of default [global variables](jinja/globals.py) and [filters](jinja/filters.py). You can register additional extensions, globals, or filters either in a package or in your app. Typically this will be in `app/templates.py` or `<pkg>/templates.py`, which are automatically imported.

```python
# app/templates.py
from plain.templates import register_template_filter, register_template_global, register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.runtime import settings


@register_template_filter
def camel_case(value):
    return value.replace("_", " ").title().replace(" ", "")


@register_template_global
def app_version():
    return "1.0.0"


@register_template_extension
class HTMXJSExtension(InclusionTagExtension):
    tags = {"htmx_js"}
    template_name = "htmx/js.html"

    def get_context(self, context, *args, **kwargs):
        return {
            "csrf_token": context["csrf_token"],
            "DEBUG": settings.DEBUG,
            "extensions": kwargs.get("extensions", []),
        }
```

## Rendering templates manually

Templates can also be rendered manually using the [`Template` class](core.py#Template).

```python
from plain.templates import Template

comment_body = Template("comment.md").render({"message": "Hello, world!",})
```
