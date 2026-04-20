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
- [ServerSentEventsView](#serversenteventsview)
- [Lifecycle hooks](#lifecycle-hooks)
- [ResponseException](#responseexception)
- [Error views](#error-views)
- [View patterns](#view-patterns)
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

## Async views

Any view method defined with `async def` runs directly on the worker's event loop. This enables non-blocking I/O patterns like SSE, WebSockets, and async HTTP clients.

**Important:** Blocking calls in async views freeze the entire worker process — no other requests can be processed until the blocking call returns. Plain's ORM, sessions, and auth layers are all synchronous and must not be called directly from async views.

Common mistakes:

- `User.query.get(pk=1)` — blocks the event loop
- `time.sleep(1)` — use `await asyncio.sleep(1)` instead
- `requests.get(...)` — use an async HTTP client instead

To wrap a blocking call safely: `await asyncio.get_running_loop().run_in_executor(None, blocking_fn)`

Use async views only for true async I/O (SSE, async HTTP clients). For standard request/response views that use the ORM, use regular sync views — they run in the thread pool and don't block other connections.

In development (`DEBUG=True`), the server enables asyncio debug mode which logs warnings when a callback blocks the event loop for more than 100ms.

## ServerSentEventsView

[`ServerSentEventsView`](./sse.py#ServerSentEventsView) provides [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) streaming. Subclass it and implement `stream()` as an async generator.

```python
import asyncio
from datetime import datetime
from plain.views import ServerSentEvent, ServerSentEventsView


class ClockView(ServerSentEventsView):
    async def stream(self):
        while True:
            yield ServerSentEvent(data={"time": datetime.now().isoformat()})
            await asyncio.sleep(1)
```

The `stream()` method must yield `ServerSentEvent` instances. The `data` argument accepts strings, dicts, and lists (dicts/lists are JSON-serialized). You can also set optional `event`, `id`, and `retry` fields.

```python
from plain.views import ServerSentEvent


class NotificationView(ServerSentEventsView):
    async def stream(self):
        yield ServerSentEvent(data="hello")                        # Simple string
        yield ServerSentEvent(data={"count": 1})                   # JSON data
        yield ServerSentEvent(data="update", event="status")       # Named event type
        yield ServerSentEvent(data="msg", id="42", retry=5000)     # With id and retry
        yield ServerSentEvent.comment("keepalive")                 # SSE comment (keepalive)
```

Connect from JavaScript using the standard [`EventSource`](https://developer.mozilla.org/en-US/docs/Web/API/EventSource) API:

```javascript
const source = new EventSource("/events/");
source.onmessage = (event) => {
    console.log(event.data);
};
// Listen for named event types
source.addEventListener("status", (event) => {
    console.log("Status:", event.data);
});
```

Send `ServerSentEvent.comment()` periodically as a keepalive to prevent proxies and browsers from closing idle connections.

ServerSentEventsView only accepts GET requests. The `stream()` method runs on the event loop — use `await` for any I/O and avoid blocking calls. Use `await asyncio.sleep()` instead of `time.sleep()`, and `await loop.run_in_executor()` to wrap blocking operations.

Note: browsers limit HTTP/1.1 to 6 SSE connections per domain. Use HTTP/2 to avoid this limit.

## Lifecycle hooks

Every view has three hooks around its handler: `before_request` runs before the HTTP method handler, `after_response` runs after the response is built (including error responses), and `handle_exception` converts any exception raised during dispatch into a response.

### `before_request`

Runs before the HTTP method handler (`get`, `post`, etc.). Default is a no-op. Raise to reject the request — the exception flows through `handle_exception`.

```python
from plain.http import ForbiddenError403

class MyView(View):
    def before_request(self):
        if self.request.user and self.request.user.is_banned:
            raise ForbiddenError403("Banned")
```

Use it for auth checks, rate limiting, or any precondition. `AuthView` overrides it to call `check_auth()`; `APIKeyView` uses it to validate the API key.

### `after_response`

Runs after the response is built — for successes, responses from `handle_exception`, and 405 method-not-allowed. Return the response (mutated or replaced). Default is a no-op.

```python
from plain.http import ResponseBase
from plain.utils.cache import patch_cache_control

class MyView(View):
    def after_response(self, response: ResponseBase) -> ResponseBase:
        patch_cache_control(response, private=True)
        return response
```

Exceptions raised inside `after_response` are not routed through `handle_exception` — they escape to the framework's error renderer. Guard in `before_request` or inside the handler for anything that might raise.

### `handle_exception`

Converts an exception raised during `before_request` or the handler into a response. Subclasses override it to format errors for their clients.

```python
from plain.http import ResponseBase

class MyView(View):
    def handle_exception(self, exc: Exception) -> ResponseBase:
        if isinstance(exc, MyAppError):
            return JsonResponse({"error": str(exc)}, status_code=400)
        return super().handle_exception(exc)
```

The framework's default renders `{status}.html` ([`Error views`](#error-views)) — most views don't need to override this hook. Override when you want a non-HTML format: `APIView` emits JSON. The base `View.handle_exception` re-raises, so unhandled cases fall through to the framework default.

`ResponseException` is unwrapped by `get_response` before `handle_exception` runs, so you don't need to handle it in overrides. The exception is logged once — before `handle_exception` is called — so overrides focus purely on response shape, not observability.

Plain's HTTP exceptions (`NotFoundError404`, `ForbiddenError403`, `BadRequestError400`, etc.) inherit [`HTTPException`](../http/exceptions.py#HTTPException) and carry their own `status_code`. Subclass `HTTPException` to define your own:

```python
from plain.http import HTTPException

class PaymentRequiredError402(HTTPException):
    status_code = 402
```

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

HTTP errors are rendered from templates named after the status code:

- `templates/404.html` - Page not found
- `templates/403.html` - Forbidden
- `templates/500.html` - Server error

Plain looks for `{status_code}.html` and renders it with `request`, `status_code`, and `exception` in context. If the template is missing or fails to render, a plain-text body is returned (`404 Not Found`, `500 Internal Server Error`, etc.). Most apps only need the three templates above.

This covers every error source — exceptions raised inside views, URL resolution failures, middleware errors — so `404.html` renders for any 404, not just ones raised from your own code. Views that want a different format (e.g. JSON for an API) override `handle_exception` to opt out.

Your `500.html` template should be self-contained. Avoid extending base templates or accessing the database/session, since server errors can occur during middleware or template rendering. `404.html` and `403.html` can safely extend base templates since they occur during view execution after middleware runs.

## View patterns

### Don't evaluate querysets at class level

Class attributes execute at import time, not per request. Queries belong in methods.

```python
# Bad — runs once at import, stale forever
class DashboardView(View):
    recent_users = User.query.order_by("-created_at")[:5]

# Good — fresh per request
class DashboardView(View):
    def get_template_context(self):
        return {"recent_users": User.query.order_by("-created_at")[:5]}
```

### Paginate list views

Always paginate querysets in list views. Unbounded queries get slower as data grows.

```python
from plain.paginator import Paginator

def get_template_context(self):
    paginator = Paginator(Item.query.all(), per_page=25)
    page = paginator.get_page(self.request.query_params.get("page"))
    return {"page": page}
```

### Wrap multi-step writes in transactions

Use `transaction.atomic()` when creating or updating related objects together.

```python
from plain.postgres import transaction

with transaction.atomic():
    order = Order(user=user)
    order.save()
    payment = Payment(order=order, amount=total)
    payment.save()
```

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

URL parameters are available via `self.url_kwargs`.

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
