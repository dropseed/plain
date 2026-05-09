# Schema

`plain.schema.Schema` is Plain's validation primitive. Pure parser — takes a dict, returns either a typed schema instance or `Invalid`. Works in views, jobs, scripts, tests; not bound to a request.

## Declare with annotations + types

```python
from plain.schema import Schema, types

class ContactSchema(Schema):
    email: str = types.EmailField()
    message: str = types.TextField(max_length=2000)
    notes: str | None = types.TextField(required=False)
```

The annotation drives type-checker visibility into `result.<field>`; `types.*` drives runtime validation. Mirrors `plain.postgres.types`.

## Validate and narrow

The schema class plays double duty: `validate()` returns either an instance of the schema (success) or `Invalid` (failure). Eliminate `Invalid` to narrow into the typed instance — no `.data` indirection.

```python
from plain.schema import Invalid

result = ContactSchema.validate(self.request.json_data)
if isinstance(result, Invalid):
    return JsonResponse({"errors": result.errors}, status_code=400)
# `result` IS the typed ContactSchema — attribute access is statically checked
contact = result
contact.email   # str
```

## When to reach for Schema vs Form vs inline

- **Schema** — JSON APIs, HTMX actions, job payloads, webhooks, CLI scripts, tests. Anything that isn't an HTML edit page.
- **Form** (`plain.forms`) — full HTML pages with template-bound fields, `prefix=`, GET/POST render-with-errors round-trip.
- **Inline field** — trivial single-value parsing: `types.IntegerField(min_value=1).clean(value)`.

If you're tempted to `request.json_data["x"]` and then check it — write a Schema instead. If you're rendering an HTML form back with errors — use Form, or pair Schema with `BoundSchema` for the rendering.

## Cross-field validation via `check()`

Override `check()` as an instance method — `self` is the typed instance, no Liskov ignore needed.

```python
class TaskSchema(Schema):
    is_complete: bool = types.BooleanField(required=False)
    completed_at: datetime | None = types.DateTimeField(required=False)

    def check(self, *, context=None):
        if self.is_complete and not self.completed_at:
            return {"completed_at": ["Required when is_complete is True."]}
        return None
```

Returns a per-field errors dict (use `"__all__"` for non-field errors), or raises `ValidationError`. Runs after every field has cleaned.

## OpenAPI integration

Pass a Schema to `openapi.schema_body(SchemaClass)` for the request body, or use it as a return-type annotation for auto-generated 200 responses. Same declaration, two outputs (validation + docs).

Run `uv run plain docs schema` for full patterns. Run `uv run plain docs schema --api` for the public API surface.
