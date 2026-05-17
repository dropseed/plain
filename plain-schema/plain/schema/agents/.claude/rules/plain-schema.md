# Schema

`plain.schema.Schema` is a validation primitive. Pure parser — takes a dict, returns either a typed schema instance or `Invalid`. Works in views, jobs, scripts, tests; not bound to a request, doesn't render HTML, doesn't touch a database.

## Declare with `types`

```python
from plain.schema import Schema, types

class ContactSchema(Schema):
    email = types.EmailField()
    message = types.TextField(max_length=2000)
    notes = types.TextField(required=False)
```

No annotations — the `types.*` constructors are typed, so the checker infers everything. Each field is a descriptor: `ContactSchema.email` is the typed reference `Field[str]`, `result.email` is the cleaned value `str`. `required=False` makes the cleaned value optional (`result.notes` is `str | None`).

## Validate and narrow

`validate()` returns either an instance of the schema (success) or `Invalid` (failure) — never raises on validation failure. Eliminate `Invalid` to narrow into the typed instance — no `.data` indirection.

```python
from plain.schema import Invalid

result = ContactSchema.validate(self.request.json_data)
if isinstance(result, Invalid):
    return JsonResponse({"errors": result.errors}, status_code=400)
# `result` IS the typed ContactSchema — attribute access is statically checked
contact = result
contact.email   # str
```

- `Invalid.errors` is `dict[str, list[str]]` (`"__all__"` holds non-field errors); `Invalid.raw` preserves the input.
- `validate_partial(data)` checks only the fields present — skips missing-field errors and `check()`, returns `Invalid | None` (never a schema instance). For HTMX live validation.
- `validate(data, files=request.files)` populates `FileField`/`ImageField` from uploads.

## Cross-field validation via `check()`

Override `check()` as an instance method — `self` is the typed instance. Runs after every field has cleaned.

```python
def check(self, *, context=None):
    if self.is_complete and not self.completed_at:
        return {"completed_at": ["Required when is_complete is True."]}
    return None
```

Return a per-field errors dict (`"__all__"` for non-field errors), or `None` when valid. Return — don't raise: a schema is a non-raising parser, and `check()` follows the same contract as `validate()`.

## When to reach for Schema vs inline

- **Schema** — JSON APIs, HTMX actions, job payloads, webhooks, CLI scripts, tests, HTML pages via `SchemaForm`.
- **Inline field** — trivial single-value parsing: `types.IntegerField(min_value=1).clean(value)`.

If you're tempted to `request.json_data["x"]` and then check it — write a Schema instead.

## Model-backed input

For input backed by a `postgres.Model`, subclass `ModelSchema` (`from plain.schema.modelschema import ModelSchema, model_field` — not re-exported at the package top level, so it doesn't pull `plain.postgres` into a plain `Schema` import): set `model = X` and declare each field as `name: Field[T] = model_field()`. Unlike a plain `Schema`, the `Field[T]` annotation is required here — `model_field()` is a placeholder, so the type comes from the annotation. Each derives from the model column of the same name — scalars become `types.*`, a ForeignKey a `ModelChoiceField`, a ManyToMany a `ModelMultipleChoiceField` — and `ModelSchema.name` is a typed reference like any schema field. `save(instance)` persists; `with_querysets(field=qs, ...)` returns a subclass with FK/M2M scoped (multi-tenant).

## HTML rendering

`SchemaForm` pairs a schema with the request — the HTML form-cycle primitive. `submit()` returns `Schema | Invalid`; on `Invalid` the form rebinds, so re-rendering shows the submitted values + per-field errors.

- `SchemaFormView` (`from plain.schema.views import SchemaFormView`) — for a view that's _just_ a form: set `schema_class`, implement `on_valid(result)`, optionally override `get_schema_form()`. It's a `TemplateView`, so mix in `AuthView` etc. Not re-exported at the package top level.
- When a view is more than a form (HTMX actions, multi-step), skip the base — drive `SchemaForm` from your own `.get()`/`.post()` on a `TemplateView`, rendering with `render(**context)`.
- For a `ModelSchema`: `querysets={...}` scopes FK/M2M (multi-tenant); `initial=ModelSchema.initial_from(instance)` pre-fills an edit form.
- Templates index the form by typed reference — `form[schema.email]` → a bound field with `.name`, `.value()`, `.errors`, `.field`. Pass the schema class to the template as `schema`.
- JSON/MCP and other non-HTML surfaces skip `SchemaForm` — call `Schema.validate()` directly.

Run `uv run plain docs schema` for full patterns. Run `uv run plain docs schema --api` for the public API surface.
