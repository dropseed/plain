# Schema

`plain.schema.Schema` is a validation primitive. Pure parser — takes a dict, returns either a typed schema instance or `Invalid`. Works in views, jobs, scripts, tests; not bound to a request, doesn't render HTML, doesn't touch a database.

## Declare with `Field[T]` + types

```python
from plain.schema import Field, Schema, types

class ContactSchema(Schema):
    email: Field[str] = types.EmailField()
    message: Field[str] = types.TextField(max_length=2000)
    notes: Field[str | None] = types.TextField(required=False)
```

Each field is a descriptor: `ContactSchema.email` is the typed reference `Field[str]`, `result.email` is the cleaned value `str`. Annotate as `Field[T]`; `types.*` drives runtime validation. For optional fields use `Field[T | None]` with `required=False`.

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
- `validate(data, partial=True)` skips missing-field errors and `check()` — for HTMX live validation.
- `validate(data, files=request.files)` populates `FileField`/`ImageField` from uploads.

## Cross-field validation via `check()`

Override `check()` as an instance method — `self` is the typed instance. Runs after every field has cleaned.

```python
def check(self, *, context=None):
    if self.is_complete and not self.completed_at:
        return {"completed_at": ["Required when is_complete is True."]}
    return None
```

Return a per-field errors dict, or raise `ValidationError`.

## When to reach for Schema vs inline

- **Schema** — JSON APIs, HTMX actions, job payloads, webhooks, CLI scripts, tests, HTML pages backed by `BoundSchema`.
- **Inline field** — trivial single-value parsing: `types.IntegerField(min_value=1).clean(value)`.

If you're tempted to `request.json_data["x"]` and then check it — write a Schema instead.

## Model-backed input

For input backed by a `postgres.Model`, subclass `ModelSchema` (`from plain.schema.modelschema import ModelSchema` — not re-exported at the package top level, so it doesn't pull `plain.postgres` into a plain `Schema` import): set `model = X` and annotate the fields to expose. Fields auto-derive — scalars become `types.*`, a ForeignKey becomes a `ModelChoiceField`, a ManyToMany a `ModelMultipleChoiceField`. `save(instance)` persists; `with_querysets(field=qs, ...)` returns a subclass with FK/M2M scoped (multi-tenant).

## HTML rendering

Pair with `BoundSchema` for template rendering — `BoundSchema(SchemaClass)` for a blank form, `BoundSchema.from_invalid(SchemaClass, result)` to re-render after a failed POST. Its field surface is duck-compatible with `plain.forms.BoundField`, so existing form templates render unchanged.

For full HTML pages, use `SchemaFormView[MySchema]` (`from plain.schema.views import SchemaFormView` — not re-exported at the package top level, so it doesn't pull `plain.templates` into a plain `Schema` import) — the schema counterpart to `FormView`. Set `schema_class` + `success_url`, override `schema_valid(result)` to persist.

Run `uv run plain docs schema` for full patterns. Run `uv run plain docs schema --api` for the public API surface.
