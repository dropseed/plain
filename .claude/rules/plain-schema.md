# Schema

`plain.schema.Schema` is a validation primitive. Pure parser — takes a dict, returns either a typed schema instance or `Invalid`. Works in views, jobs, scripts, tests; not bound to a request, doesn't render HTML, doesn't touch a database.

## Declare with annotations + types

```python
from plain.schema import Schema, types

class ContactSchema(Schema):
    email: str = types.EmailField()
    message: str = types.TextField(max_length=2000)
    notes: str | None = types.TextField(required=False)
```

The annotation drives type-checker visibility into `result.<field>`; `types.*` drives runtime validation. For optional fields use `T | None` with `required=False`.

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

## HTML rendering

Pair with `BoundSchema` for template rendering — `BoundSchema(SchemaClass)` for a blank form, `BoundSchema.from_invalid(SchemaClass, result)` to re-render after a failed POST. Its field surface is duck-compatible with `plain.forms.BoundField`, so existing form templates render unchanged.

Run `uv run plain docs schema` for full patterns. Run `uv run plain docs schema --api` for the public API surface.
