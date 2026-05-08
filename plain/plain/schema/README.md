# Schema

**Validating parsers for typed Python data — works in views, jobs, scripts, anywhere a dict needs to become typed Python data.**

A `Schema` declares fields with type annotations and validators; `.validate(data)` returns `Valid[Self] | Invalid` — a sum type that narrows under `isinstance` without asserts. Schemas don't take a request, don't render HTML, and don't save to a database. They're the validation primitive Plain uses across packages.

- [Overview](#overview)
- [Declaring schemas](#declaring-schemas)
- [Inline schemas](#inline-schemas)
- [The `Result` type](#the-result-type)
- [Type narrowing](#type-narrowing)
- [Cross-field validation](#cross-field-validation)
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

# result.data is statically typed as ContactSchema
contact = result.data
contact.email     # str
contact.message   # str
```

The Schema class is the parser; `result.data` is the typed cleaned instance. Validation is a pure function call — no request, no `.is_valid()` dance, no `cleaned_data` dict.

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

The annotation drives type-checker visibility into `result.data.<field>`; the `types.*` instance drives runtime parsing and validation. This mirrors `plain.postgres.types` for models — same pattern, same ergonomics.

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

Inline schemas trade ergonomics for typing — `result.data` is opaque (`object`) because the class doesn't exist statically. Promote to a named class when you want typed `result.data` access.

## The `Result` type

`Schema.validate()` always returns a value, never raises:

```python
@dataclass(frozen=True)
class Valid[T]:
    data: T              # the typed schema instance
    raw: dict            # original input

@dataclass(frozen=True)
class Invalid:
    errors: dict[str, list[str]]   # JSON-ready, per-field
    raw: dict                      # original input
```

`errors` shape is canonical: a dict from field name to a list of message strings. The special key `"__all__"` carries non-field (cross-field) errors. Drops straight into a JSON response or template renderer.

## Type narrowing

The reliable narrowing pattern is to **eliminate `Invalid` first**:

```python
result = TaskSchema.validate(payload)
if isinstance(result, Invalid):
    return JsonResponse({"errors": result.errors}, status_code=400)
# result is now Valid[TaskSchema]; result.data is TaskSchema, fully typed
do_stuff(result.data.title)
```

Or as an early `assert`:

```python
result = TaskSchema.validate(payload)
assert not isinstance(result, Invalid)
contact = result.data    # TaskSchema, fully typed
```

**Avoid `isinstance(result, Valid)` directly.** Narrowing into a generic class doesn't preserve the type parameter under `ty`, so `result.data` falls back to `object`. Always narrow by eliminating `Invalid`.

## Cross-field validation

Override `check()` for validation that needs to see multiple fields at once. It runs after every field has cleaned successfully and receives the typed instance:

```python
class TaskSchema(Schema):
    title: str = types.TextField(max_length=200)
    is_complete: bool = types.BooleanField(required=False)
    completed_at: datetime | None = types.DateTimeField(required=False)

    @classmethod
    def check(cls, data, *, context=None):
        if data.is_complete and not data.completed_at:
            return {"completed_at": ["Required when is_complete is True."]}
        return None
```

`check()` can also raise `ValidationError` — the dict-form unpacks per-field, the string-form attaches to `"__all__"`. Both styles produce the same `Invalid.errors` shape.

The `context` kwarg flows through from the call site:

```python
result = TaskSchema.validate(payload, context={"user_id": user.id})
```

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
        # result.data.title, result.data.priority, etc — all typed
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

- **`Schema`** — parsing + validating typed input. Use everywhere: HTML forms, JSON APIs, HTMX actions, job payloads, webhook handlers, CLI scripts, tests. Never bound to a request.
- **`Form`** (in `plain.forms`) — full HTML edit pages where you need template binding, `BoundField`, prefixed multi-form pages, and the GET/POST render-with-errors round-trip.

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
from plain.schema import Schema, Valid, Invalid, types, make_schema
```
