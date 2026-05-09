# Schema

**Validating parsers for typed Python data — works in views, jobs, scripts, anywhere a dict needs to become typed Python data.**

A `Schema` declares fields with type annotations and validators; `.validate(data)` returns either an instance of the schema (success) or an `Invalid` carrying per-field errors. Eliminate `Invalid` with `isinstance` to narrow into the typed instance — no `.data` indirection. Schemas don't take a request, don't render HTML, and don't save to a database. They're the validation primitive Plain uses across packages.

- [Overview](#overview)
- [Declaring schemas](#declaring-schemas)
- [Inline schemas](#inline-schemas)
- [The `Invalid` result](#the-invalid-result)
- [Type narrowing](#type-narrowing)
- [Cross-field validation](#cross-field-validation)
- [Partial validation](#partial-validation)
- [File uploads](#file-uploads)
- [HTML rendering with BoundSchema](#html-rendering-with-boundschema)
- [OpenAPI integration](#openapi-integration)
- [When to use Schema vs Form](#when-to-use-schema-vs-form)
- [Installation](#installation)

## Overview

```python
from plain.schema import Schema, Invalid, types

class ContactSchema(Schema):
    email: str = types.EmailField()
    message: str = types.TextField(max_length=2000)

result = ContactSchema.validate({"email": "a@b.co", "message": "hi"})
if isinstance(result, Invalid):
    return JsonResponse({"errors": result.errors}, status_code=400)

# `result` IS the typed ContactSchema instance.
contact = result
contact.email     # str
contact.message   # str
```

The Schema class is the parser; the validated instance IS the schema (no `.data` wrapper). Validation is a pure function call — no request, no `.is_valid()` dance.

## Declaring schemas

Subclass `Schema` and declare fields with type annotations plus a `types.*` field instance:

```python
from plain.schema import Schema, types

class TaskSchema(Schema):
    title: str = types.TextField(max_length=200, min_length=1)
    notes: str | None = types.TextField(required=False)
    priority: str = types.ChoiceField(choices=[("low", "Low"), ("high", "High")])
    is_complete: bool = types.BooleanField(required=False)
```

The annotation drives type-checker visibility into `result.<field>`; the `types.*` instance drives runtime parsing and validation. This mirrors `plain.postgres.types` for models — same pattern, same ergonomics.

For optional fields, use `T | None` and `required=False` together — the `.pyi` stub overloads make this consistent.

## Inline schemas

Build a one-off schema as a value when a class would be ceremony:

```python
from plain.schema import make_schema, types

result = make_schema(
    page=types.IntegerField(min_value=1, default=1),
    search=types.TextField(required=False),
).validate(request.query_params)
```

Inline schemas trade ergonomics for typing — the validated instance is opaque (`Schema`) because the class doesn't exist statically. Promote to a named class when you want typed attribute access on the result.

## The `Invalid` result

```python
@dataclass(frozen=True)
class Invalid:
    errors: dict[str, list[str]]   # JSON-ready, per-field
    raw: dict                      # original input — preserved for re-rendering
```

`errors` shape is canonical: a dict from field name to a list of message strings. The special key `"__all__"` carries non-field (cross-field) errors. Drops straight into a JSON response or template renderer.

## Type narrowing

The reliable narrowing pattern is to **eliminate `Invalid` first**:

```python
result = TaskSchema.validate(payload)
if isinstance(result, Invalid):
    return JsonResponse({"errors": result.errors}, status_code=400)
# result is now TaskSchema; attribute access is statically checked
do_stuff(result.title)
```

Or as an early `assert`:

```python
result = TaskSchema.validate(payload)
assert not isinstance(result, Invalid)
contact = result    # TaskSchema, fully typed
```

The schema-class-as-validated-instance design means `result.title` works directly without `.data` indirection. Narrowing is straightforward because `Invalid` is non-generic.

## Cross-field validation

Override `check()` as an instance method on the schema. `self` is the typed instance with all cleaned values set, so attribute access in the override is naturally typed.

```python
class TaskSchema(Schema):
    title: str = types.TextField(max_length=200)
    is_complete: bool = types.BooleanField(required=False)
    completed_at: datetime | None = types.DateTimeField(required=False)

    def check(self, *, context=None):
        if self.is_complete and not self.completed_at:
            return {"completed_at": ["Required when is_complete is True."]}
        return None
```

`check()` can also raise `ValidationError` — the dict-form unpacks per-field, the string-form attaches to `"__all__"`. Both styles produce the same `Invalid.errors` shape.

The `context` kwarg flows through from the call site:

```python
result = TaskSchema.validate(payload, context={"user_id": user.id})
```

## Partial validation

For HTMX live-validation, where each keystroke sends just one field, pass `partial=True` to skip required-errors on missing fields. `check()` is also skipped (it can't run on a subset).

```python
def htmx_post_validate(self):
    result = TaskSchema.validate(self.request.form_data, partial=True)
    if isinstance(result, Invalid):
        return JsonResponse({"valid": False, "errors": result.errors})
    return JsonResponse({"valid": True})
```

## File uploads

Pass `request.files` as the `files=` kwarg to validate uploads. `FileField` and `ImageField` declarations populate from `files`; everything else continues to read from `data`.

```python
class AttachmentSchema(Schema):
    description: str = types.TextField(max_length=500)
    document: Any = types.FileField(max_length=120)

class UploadView(View):
    def post(self):
        result = AttachmentSchema.validate(
            self.request.form_data,
            files=self.request.files,
        )
        if isinstance(result, Invalid):
            return self.render_errors(result.errors)
        # result.document is the UploadedFile; result.description is str.
        ...
```

`partial=True` includes `files` in its presence check, so HTMX live-validate can also handle file fields.

## HTML rendering with BoundSchema

When you need template binding (full HTML edit pages), pair the schema with a `BoundSchema`:

```python
from plain.schema import BoundSchema, Invalid

class ContactView(View):
    def get(self):
        bound = BoundSchema(schema_class=ContactSchema, initial={"email": user.email})
        return self.render(form=bound)

    def post(self):
        result = ContactSchema.validate(self.request.form_data)
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(ContactSchema, result)
            return self.render(form=bound)
        # use result.email, result.message, etc.
        ...
```

The bound form's duck-typed surface (`html_id`, `html_name`, `value()`, `errors`, `field`, `non_field_errors`, `fields`) matches `plain.forms.BoundField`, so existing form templates render against `BoundSchema` unchanged.

## OpenAPI integration

When `plain-api` is installed, schemas drive both runtime validation AND OpenAPI documentation. Same declaration, two outputs:

```python
from plain.api import openapi
from plain.api.views import APIView

class TaskCreateView(APIView):
    @openapi.schema({
        "summary": "Create a task.",
        "requestBody": openapi.schema_body(TaskSchema),
        "responses": {"201": {"description": "Created."}},
    })
    def post(self) -> tuple[int, dict]:
        result = TaskSchema.validate(self.request.json_data)
        if isinstance(result, Invalid):
            return 400, {"errors": result.errors}
        # result.title, result.priority, etc — all typed
        ...
```

`schema_from_type(SchemaClass)` produces an OpenAPI object schema — properties from fields, `required` list from required flags, constraints (`maxLength`, `minimum`, `enum` from choices) from declared field options.

A return-type annotation pointing at a Schema auto-generates the 200 response too:

```python
class TaskOut(Schema):
    id: int = types.IntegerField()
    title: str = types.TextField()

class TaskGetView(APIView):
    def get(self) -> TaskOut:                # auto-200 schema in OpenAPI doc
        ...
```

## When to use Schema vs Form

Different jobs:

- **`Schema`** — parsing + validating typed input. Use everywhere: HTML forms (paired with `BoundSchema`), JSON APIs, HTMX actions, job payloads, webhook handlers, CLI scripts, tests. Never bound to a request.
- **`Form`** (in `plain.forms`) — the existing class-based form with `BoundField`, prefixed multi-form pages, and the GET/POST render-with-errors round-trip. Largely supplanted by Schema + BoundSchema for new code.

If your endpoint isn't rendering an HTML form back to the user, you don't need `Form` — reach for `Schema`. That includes:

- JSON API endpoints
- HTMX action handlers (`htmx_post_*`)
- Background job payload validation
- Webhook receivers
- One-off `validate()` calls in tests / scripts

Inline parsing of a single field is also fine for trivial cases:

```python
pin_id = types.IntegerField(min_value=1).clean(request.form_data["pin_id"])
```

## Installation

`plain.schema` ships with `plain` — no separate install. Import the public surface:

```python
from plain.schema import Schema, Invalid, types, BoundSchema, make_schema
```
