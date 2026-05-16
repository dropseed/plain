# Schema

**Validating parsers for typed Python data — works in views, jobs, scripts, anywhere a dict needs to become typed Python data.**

A `Schema` declares fields with type annotations and validators; `.validate(data)` returns either an instance of the schema (success) or an `Invalid` carrying per-field errors. Eliminate `Invalid` with `isinstance` to narrow into the typed instance — no `.data` indirection. Schemas don't take a request, don't render HTML, and don't save to a database. They're a standalone validation primitive.

- [Overview](#overview)
- [Declaring schemas](#declaring-schemas)
- [Inline schemas](#inline-schemas)
- [The `Invalid` result](#the-invalid-result)
- [Type narrowing](#type-narrowing)
- [Cross-field validation](#cross-field-validation)
- [Partial validation](#partial-validation)
- [File uploads](#file-uploads)
- [HTML rendering with BoundSchema](#html-rendering-with-boundschema)
- [SchemaView](#schemaview)
- [ModelSchema](#modelschema)
- [Property tests with Hypothesis](#property-tests-with-hypothesis)
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

The bound form's duck-typed surface (`html_id`, `html_name`, `value()`, `errors`, `field`, `non_field_errors`, `fields`) is the same surface `plain.forms.BoundField` exposes — existing form templates render against `BoundSchema` unchanged.

## SchemaView

For full HTML pages, [`SchemaView`](./views.py#SchemaView) wraps the GET-render / POST-validate / re-render-or-redirect cycle — the schema counterpart to `plain.templates`' `FormView`. Set `schema_class` and `success_url`, and override `schema_valid()` to do something with the validated result:

```python
from plain.schema.views import SchemaView

from .schemas import ContactSchema


class ContactView(SchemaView[ContactSchema]):
    template_name = "contact.html"
    schema_class = ContactSchema
    success_url = "/thanks/"

    def schema_valid(self, result):
        # `result` is a validated ContactSchema — a pure parser, no `.save()`.
        # `apply_to` copies the cleaned values onto a record; the view persists.
        result.apply_to(ContactSubmission()).save()
        return super().schema_valid(result)
```

Parameterize as `SchemaView[ContactSchema]` so `result` is typed in `schema_valid()`. The template receives the schema as `form` (a `BoundSchema`), so it renders with the same field markup a `FormView` template uses.

> `SchemaView` lives in `plain.schema` for now — while the schema view design is still being iterated on — even though it makes this package depend on `plain.templates`. It's imported from its own module (`from plain.schema.views import SchemaView`) and not re-exported at the package top level, so a plain `from plain.schema import Schema` doesn't load the template layer.

## ModelSchema

[`ModelSchema`](./modelschema.py#ModelSchema) is the schema counterpart to `plain.postgres`' `ModelForm`. Declare a `model` and annotate the fields to expose — the metaclass derives a validating field for each one:

```python
from plain.schema.modelschema import ModelSchema

from .models import Project, Tag, Task


class TaskSchema(ModelSchema):
    model = Task

    title: str                  # scalar columns → types.* fields
    project: Project | None      # ForeignKey      → ModelChoiceField
    tags: list[Tag]              # ManyToMany      → ModelMultipleChoiceField
    is_complete: bool
```

Scalar columns map to the matching `types.*` field; a `ForeignKeyField` becomes a `ModelChoiceField` (a primary key cleans to the model instance) and a `ManyToManyField` becomes a `ModelMultipleChoiceField` (a list of pks cleans to a list of instances). Annotate only what you want exposed — unlisted columns (like an `owner` FK) are left for the caller to set. Override an auto-derived field by declaring a `types.*` field explicitly, and add cross-field rules with `check()`.

`save()` applies the validated values to a model instance and persists it (M2M relations are assigned after the row has a primary key):

```python
result = TaskSchema.validate(request.json_data)
if not isinstance(result, Invalid):
    result.save(Task(owner=request.user))
```

For multi-tenant FK/M2M scoping, `with_querysets()` returns a subclass whose relation querysets are narrowed — the scoped class drives both validation and the rendered `<select>` options, so a user can neither submit nor see another tenant's rows:

```python
TaskSchema.with_querysets(
    project=Project.query.filter(owner=user),
    tags=Tag.query.filter(owner=user),
)
```

> Like `SchemaView`, `ModelSchema` lives in `plain.schema` for now — it makes the package additionally depend on `plain.postgres`. It's imported from its own module (`from plain.schema.modelschema import ModelSchema`) and not re-exported at the package top level, so a plain `from plain.schema import Schema` doesn't load the ORM.

## Property tests with Hypothesis

`plain.schema.testing.schema_strategy()` produces a Hypothesis strategy that generates valid input dicts for any schema. Useful for fuzz-testing endpoints — every keystroke shouldn't produce a 500.

```python
from hypothesis import given
from plain.schema.testing import schema_strategy

@given(payload=schema_strategy(MySchema))
def test_view_handles_any_valid_payload(client, payload):
    response = client.post("/api/things/", data=payload)
    assert response.status_code == 201
```

The strategy walks the schema fields and emits constrained values per type — `IntegerField(min_value, max_value)` becomes `st.integers(min, max)`, `ChoiceField(choices=...)` becomes `st.sampled_from(...)`, and so on. Optional fields (`required=False`) are randomly omitted. `FileField`/`ImageField`/`JSONField` raise `NotImplementedError` — build a custom strategy for those and merge with the schema's other fields.

`hypothesis` is not a Plain dependency; install it as a dev dependency to use this module.

## When to use Schema vs inline

- **`Schema`** — anything that turns a dict into typed Python data: JSON APIs, HTMX actions, job payloads, webhooks, full HTML pages backed by `BoundSchema`, CLI scripts, tests.
- **Inline field** — trivial single-value parsing for cases where a class is overkill:
    ```python
    pin_id = types.IntegerField(min_value=1).clean(request.form_data["pin_id"])
    ```

If you're tempted to `request.json_data["x"]` and then check it manually — write a Schema instead.

## Installation

Install the `plain.schema` package:

```bash
uv add plain.schema
```

`plain.schema` is a pure library — there's no `INSTALLED_PACKAGES` entry or settings to configure. Import the public surface and use it anywhere:

```python
from plain.schema import Schema, Invalid, types, BoundSchema, make_schema
```
