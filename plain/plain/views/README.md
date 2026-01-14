# Views

**Take a request, return a response.**

- [Overview](#overview)
- [HTTP methods map to class methods](#http-methods-map-to-class-methods)
- [Return types](#return-types)
- [TemplateView](#templateview)
- [FormView](#formview)
- [Object views](#object-views)
    - [DetailView](#detailview)
    - [CreateView](#createview)
    - [UpdateView](#updateview)
    - [DeleteView](#deleteview)
    - [ListView](#listview)
- [RedirectView](#redirectview)
- [ResponseException](#responseexception)
- [Error views](#error-views)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain views are class-based, with a straightforward API that keeps simple views simple while giving you the full power of a class for complex cases.

```python
from plain.views import View


class ExampleView(View):
    def get(self):
        return "<html><body>Hello, world!</body></html>"
```

You can return strings, dicts, lists, integers (status codes), or full `Response` objects. Plain automatically converts them to the appropriate HTTP response.

## HTTP methods map to class methods

The HTTP method of the request maps directly to a class method of the same name. Define only the methods you want to support.

```python
from plain.views import View


class ExampleView(View):
    def get(self):
        pass

    def post(self):
        pass

    def put(self):
        pass

    def patch(self):
        pass

    def delete(self):
        pass
```

If a request comes in for a method your view doesn't implement, Plain returns a `405 Method Not Allowed` response automatically.

The [base `View` class](./base.py#View) provides default `options` and `head` behavior, but you can override these too.

## Return types

You can return common Python types directly from view methods without wrapping them in a `Response` object.

```python
class JsonView(View):
    def get(self):
        return {"message": "Hello, world!"}


class HtmlView(View):
    def get(self):
        return "<html><body>Hello, world!</body></html>"


class StatusCodeView(View):
    def get(self):
        return 204  # No content


class TupleView(View):
    def get(self):
        return (201, {"id": 123})  # Status code + data
```

Returning `None` triggers a 404 response, which is useful when an object isn't found.

## TemplateView

For rendering templates, use [`TemplateView`](./templates.py#TemplateView). This is the base class for most other built-in view classes.

```python
from plain.views import TemplateView


class ExampleView(TemplateView):
    template_name = "example.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["message"] = "Hello, world!"
        return context
```

For simple pages that don't need custom context, you can configure `TemplateView` directly in your URL routes.

```python
from plain.views import TemplateView
from plain.urls import path, Router


class AppRouter(Router):
    routes = [
        path("/example/", TemplateView.as_view(template_name="example.html")),
    ]
```

## FormView

[`FormView`](./forms.py#FormView) handles displaying and processing [forms](/plain/plain/forms/README.md).

```python
from plain.views import FormView
from .forms import ExampleForm


class ExampleView(FormView):
    template_name = "example.html"
    form_class = ExampleForm
    success_url = "."  # Redirect to the same page

    def form_valid(self, form):
        # Do additional processing here
        return super().form_valid(form)
```

The form is automatically available in your template as `form`.

```html
{% extends "base.html" %}

{% block content %}

<form method="post">
    <!-- Render general form errors -->
    {% for error in form.non_field_errors %}
    <div>{{ error }}</div>
    {% endfor %}

    <!-- Render form fields -->
    <label for="{{ form.email.html_id }}">Email</label>
    <input
        type="email"
        name="{{ form.email.html_name }}"
        id="{{ form.email.html_id }}"
        value="{{ form.email.value() or '' }}"
        autocomplete="email"
        autofocus
        required>
    {% if form.email.errors %}
    <div>{{ form.email.errors|join(', ') }}</div>
    {% endif %}

    <button type="submit">Save</button>
</form>

{% endblock %}
```

## Object views

Plain provides views for standard CRUD operations. Each requires you to implement `get_object()` or `get_objects()` to control what data is accessed.

### DetailView

[`DetailView`](./objects.py#DetailView) displays a single object.

```python
from plain.views import DetailView


class ExampleDetailView(DetailView):
    template_name = "detail.html"

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.request.user,  # Limit access
        )
```

The object is available in your template as `object`. You can also set `context_object_name` for a more descriptive name.

### CreateView

[`CreateView`](./objects.py#CreateView) displays a form and creates a new object on successful submission.

```python
from plain.views import CreateView
from .forms import CustomCreateForm


class ExampleCreateView(CreateView):
    template_name = "create.html"
    form_class = CustomCreateForm
    success_url = "."
```

### UpdateView

[`UpdateView`](./objects.py#UpdateView) displays a form pre-populated with an existing object and saves changes on submission.

```python
from plain.views import UpdateView
from .forms import CustomUpdateForm


class ExampleUpdateView(UpdateView):
    template_name = "update.html"
    form_class = CustomUpdateForm
    success_url = "."

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.request.user,
        )
```

### DeleteView

[`DeleteView`](./objects.py#DeleteView) confirms deletion of an object. POST to delete, no form class needed.

```python
from plain.views import DeleteView


class ExampleDeleteView(DeleteView):
    template_name = "delete.html"
    success_url = "/list/"

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.request.user,
        )
```

### ListView

[`ListView`](./objects.py#ListView) displays a collection of objects.

```python
from plain.views import ListView


class ExampleListView(ListView):
    template_name = "list.html"

    def get_objects(self):
        return MyObjectClass.query.filter(
            user=self.request.user,
        )
```

The objects are available in your template as `objects`.

## RedirectView

[`RedirectView`](./redirect.py#RedirectView) redirects to another URL.

```python
from plain.views import RedirectView


class ExampleRedirectView(RedirectView):
    url = "/new-location/"
```

Set `status_code = 301` for permanent redirects (default is 302).

For simple redirects, configure the view directly in your URL routes.

```python
from plain.views import RedirectView
from plain.urls import path, Router


class AppRouter(Router):
    routes = [
        path("/old-location/", RedirectView.as_view(url="/new-location/", status_code=301)),
    ]
```

You can also redirect to a named URL using `url_name`, or preserve query parameters with `preserve_query_params=True`.

## ResponseException

At any point during request handling, you can raise a [`ResponseException`](./exceptions.py#ResponseException) to immediately return a response. This is useful for authorization checks or rate limiting in nested helper functions.

```python
from plain.views import DetailView
from plain.views.exceptions import ResponseException
from plain.http import Response


class ExampleView(DetailView):
    def get_object(self):
        if self.request.user and self.request.user.exceeds_rate_limit:
            raise ResponseException(
                Response("Rate limit exceeded", status_code=429)
            )

        return AnExpensiveObject()
```

## Error views

HTTP errors are rendered using templates. Create templates for the errors users see.

- `templates/404.html` - Page not found
- `templates/403.html` - Forbidden
- `templates/500.html` - Server error

Plain looks for `{status_code}.html` templates, then returns a plain HTTP response if not found. Most apps only need these three templates.

Templates receive `status_code` and `exception` in context.

Your `500.html` template should be self-contained. Avoid extending base templates or accessing the database/session, since server errors can occur during middleware or template rendering. `404.html` and `403.html` can safely extend base templates since they occur during view execution after middleware runs.

## FAQs

#### How do I exempt a view from CSRF protection?

Use the `CSRF_EXEMPT_PATHS` setting to specify path patterns that should bypass CSRF protection. For example:

```python
# app/settings.py
CSRF_EXEMPT_PATHS = [
    r"^/api/",  # Exempt all API routes
    r"^/webhooks/",  # Exempt webhook endpoints
]
```

#### How do I access URL parameters?

URL parameters are available via `self.url_kwargs` (keyword arguments) and `self.url_args` (positional arguments).

```python
class ExampleView(View):
    def get(self):
        user_id = self.url_kwargs["id"]
        return f"User ID: {user_id}"
```

#### How do I access the request object?

The request is available as `self.request` after the view is set up.

```python
class ExampleView(View):
    def get(self):
        return f"Path: {self.request.path}"
```

#### Can I customize view initialization?

Yes, define your own `__init__` method to accept custom arguments passed via `as_view()`.

```python
class CustomView(View):
    def __init__(self, feature_enabled=False):
        self.feature_enabled = feature_enabled


# In URLs
path("/custom/", CustomView.as_view(feature_enabled=True))
```

## Installation

Views are included with the core `plain` package. No additional installation is required.
