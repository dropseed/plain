# Views

**Take a request, return a response.**

- [Overview](#overview)
- [HTTP methods -> class methods](#http-methods---class-methods)
- [Return types](#return-types)
- [Template views](#template-views)
- [Form views](#form-views)
- [Object views](#object-views)
- [Response exceptions](#response-exceptions)
- [Error views](#error-views)
- [Redirect views](#redirect-views)
- [CSRF exempt views](#csrf-exempt-views)

## Overview

Plain views are written as classes,
with a straightforward API that keeps simple views simple,
but gives you the power of a full class to handle more complex cases.

```python
from plain.views import View


class ExampleView(View):
    def get(self):
        return "<html><body>Hello, world!</body></html>"
```

## HTTP methods -> class methods

The HTTP method of the request will map to a class method of the same name on the view.

If a request comes in and there isn't a matching method on the view,
Plain will return a `405 Method Not Allowed` response.

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

    def trace(self):
        pass
```

The [base `View` class](./base.py#View) defines default `options` and `head` behavior,
but you can override these too.

## Return types

For simple JSON responses, HTML, or status code responses,
you don't need to instantiate a `Response` object.

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
```

## Template views

The most common behavior for a view is to render a template.

```python
from plain.views import TemplateView


class ExampleView(TemplateView):
    template_name = "example.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["message"] = "Hello, world!"
        return context
```

The [`TemplateView`](./templates.py#TemplateView) is also the base class for _most_ of the other built-in view classes.

Template views that don't need any custom context can use `TemplateView.as_view()` directly in the URL route.

```python
from plain.views import TemplateView
from plain.urls import path, Router


class AppRouter(Router):
    routes = [
        path("/example/", TemplateView.as_view(template_name="example.html")),
    ]
```

## Form views

Standard [forms](../forms) can be rendered and processed by a [`FormView`](./forms.py#FormView).

```python
from plain.views import FormView
from .forms import ExampleForm


class ExampleView(FormView):
    template_name = "example.html"
    form_class = ExampleForm
    success_url = "."  # Redirect to the same page

    def form_valid(self, form):
        # Do other successfull form processing here
        return super().form_valid(form)
```

Rendering forms is done directly in the HTML.

```html
{% extends "base.html" %}

{% block content %}

<form method="post">
    <!-- Render general form errors -->
    {% for error in form.non_field_errors %}
    <div>{{ error }}</div>
    {% endfor %}

    <!-- Render form fields individually (or with Jinja helps or other concepts) -->
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

The object views support the standard CRUD (create, read/detail, update, delete) operations, plus a list view.

```python
from plain.views import DetailView, CreateView, UpdateView, DeleteView, ListView


class ExampleDetailView(DetailView):
    template_name = "detail.html"

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.user,  # Limit access
        )


class ExampleCreateView(CreateView):
    template_name = "create.html"
    form_class = CustomCreateForm
    success_url = "."


class ExampleUpdateView(UpdateView):
    template_name = "update.html"
    form_class = CustomUpdateForm
    success_url = "."

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.user,  # Limit access
        )


class ExampleDeleteView(DeleteView):
    template_name = "delete.html"
    success_url = "."

    # No form class necessary.
    # Just POST to this view to delete the object.

    def get_object(self):
        return MyObjectClass.query.get(
            id=self.url_kwargs["id"],
            user=self.user,  # Limit access
        )


class ExampleListView(ListView):
    template_name = "list.html"

    def get_objects(self):
        return MyObjectClass.query.filter(
            user=self.user,  # Limit access
        )
```

## Response exceptions

At any point in the request handling,
a view can raise a [`ResponseException`](./exceptions.py#ResponseException) to immediately exit and return the wrapped response.

This isn't always necessary, but can be useful for raising rate limits or authorization errors when you're a couple layers deep in the view handling or helper functions.

```python
from plain.views import DetailView
from plain.views.exceptions import ResponseException
from plain.http import Response


class ExampleView(DetailView):
    def get_object(self):
        if self.user and self.user.exceeds_rate_limit:
            raise ResponseException(
                Response("Rate limit exceeded", status_code=429)
            )

        return AnExpensiveObject()
```

## Error views

HTTP errors are rendered using templates. Create templates for the errors users actually see:

- `templates/404.html` - Page not found
- `templates/403.html` - Forbidden
- `templates/500.html` - Server error

Plain looks for `{status_code}.html` templates, then returns a plain HTTP response if not found. Most apps only need the three specific templates above.

Templates receive `status_code` and `exception` in context.

**Note:** `500.html` should be self-contained - avoid extending base templates or accessing database/session, since server errors can occur during middleware or template rendering. `404.html` and `403.html` can safely extend base templates since they occur during view execution after middleware runs.

## Redirect views

```python
from plain.views import RedirectView


class ExampleRedirectView(RedirectView):
    url = "/new-location/"
    permanent = True
```

Redirect views can also be used in the URL router.

```python
from plain.views import RedirectView
from plain.urls import path, Router


class AppRouter(Router):
    routes = [
        path("/old-location/", RedirectView.as_view(url="/new-location/", permanent=True)),
    ]
```

## CSRF exempt views

```python
from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin


class ExemptView(CsrfExemptViewMixin, View):
    def post(self):
        return "Hello, world!"
```
