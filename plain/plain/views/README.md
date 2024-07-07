# Views

Take a request, return a response.

Plain views are written as classes,
with a straightforward API that keeps simple views simple,
but gives you the power of a full class to handle more complex cases.

```python
from plain.views import View


class ExampleView(View):
    def get(self):
        return "Hello, world!"
```

## HTTP methods -> class methods

The HTTP methd of the request will map to a class method of the same name on the view.

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

The [base `View` class](./base.py) defines default `options` and `head` behavior,
but you can override these too.

## Return types

For simple plain text and JSON responses,
you don't need to instantiate a `Response` object.

```python
class TextView(View):
    def get(self):
        return "Hello, world!"


class JsonView(View):
    def get(self):
        return {"message": "Hello, world!"}
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

The `TemplateView` is also the base class for *most* of the other built-in view classes.

## Form views

Standard [forms](../forms) can be rendered and processed by a `FormView`.

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
    {{ csrf_input }}

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
        return MyObjectClass.objects.get(
            pk=self.url_kwargs["pk"],
            user=self.request.user,  # Limit access
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
        return MyObjectClass.objects.get(
            pk=self.url_kwargs["pk"],
            user=self.request.user,  # Limit access
        )


class ExampleDeleteView(DeleteView):
    template_name = "delete.html"
    success_url = "."

    # No form class necessary.
    # Just POST to this view to delete the object.

    def get_object(self):
        return MyObjectClass.objects.get(
            pk=self.url_kwargs["pk"],
            user=self.request.user,  # Limit access
        )


class ExampleListView(ListView):
    template_name = "list.html"

    def get_objects(self):
        return MyObjectClass.objects.filter(
            user=self.request.user,  # Limit access
        )
```

## Response exceptions

At any point in the request handling,
a view can raise a `ResponseException` to immediately exit and return the wrapped response.

This isn't always necessary, but can be useful for raising rate limits or authorization errors when you're a couple layers deep in the view handling or helper functions.

```python
from plain.views import DetailView
from plain.views.exceptions import ResponseException
from plain.http import Response


class ExampleView(DetailView):
    def get_object(self):
        if self.request.user.exceeds_rate_limit:
            raise ResponseException(
                Response("Rate limit exceeded", status=429)
            )

        return AnExpensiveObject()
```

## Error views

By default, HTTP errors will be rendered by `templates/<status_code>.html` or `templates/error.html`.

You can define your own error views by pointing the `HTTP_ERROR_VIEWS` setting to a dictionary of status codes and view classes.

```python
# app/settings.py
HTTP_ERROR_VIEWS = {
    404: "errors.NotFoundView",
}
```

```python
# app/errors.py
from plain.views import View


class NotFoundView(View):
    def get(self):
        # A custom implementation or error view handling
        pass
```

## Redirect views

```python
from plain.views import RedirectView


class ExampleRedirectView(RedirectView):
    url = "/new-location/"
    permanent = True
```

## CSRF exemption

```python
from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin


class ExemptView(CsrfExemptViewMixin, View):
    def post(self):
        return "Hello, world!"
```
