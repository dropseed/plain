# Schema

`plain.schema.Schema` is Plain's validation primitive. Pure parser — takes a dict, returns either a typed schema instance or `Invalid`. Works in views, jobs, scripts, tests; not bound to a request.

For schemas backed by a model, use `plain.postgres.modelschema.ModelSchema` (see below).

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

## ModelSchema — auto-derive from a model

For schemas backed by a `postgres.Model`, use `ModelSchema` and let it walk the model's fields. Annotation-driven, no `class Meta:`.

```python
from plain.postgres.modelschema import ModelSchema

class TaskSchema(ModelSchema):
    model = Task

    title: str
    notes: str | None
    project: Project | None        # FK → ModelChoiceField
    tags: list[Tag]                # M2M → ModelMultipleChoiceField
    is_complete: bool
```

To exclude a model field, don't annotate it. To override an auto-derived Field, provide the Field instance: `name: str = types.TextField(min_length=2)`.

For per-request queryset scoping (multi-tenant FK/M2M), pass `context["querysets"]`:

```python
result = TaskSchema.validate(
    request.json_data,
    context={"querysets": {
        "project": Project.query.filter(owner=user),
        "tags": Tag.query.filter(owner=user),
    }},
)
```

`save_to(instance)` and `save()` apply validated values and persist (M2M is set after the instance has a primary key).

## When to reach for Schema vs ModelSchema vs inline

- **Schema** — JSON APIs, HTMX actions, job payloads, webhooks, CLI scripts, tests, HTML pages backed by `BoundSchema`. Anything not bound to a model.
- **ModelSchema** — model-edit pages, admin CRUD, anywhere fields auto-derive from a `postgres.Model`. Auto-handles FK/M2M.
- **Inline field** — trivial single-value parsing: `types.IntegerField(min_value=1).clean(value)`.

If you're tempted to `request.json_data["x"]` and then check it — write a Schema instead.

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

## SchemaView for HTML pages

`plain.views.SchemaView[T]` orchestrates GET-render / POST-validate / re-render-or-redirect. `SchemaCreateView`, `SchemaUpdateView`, `SchemaDeleteView` for model-edit flows. Pair with `BoundSchema` (duck-compatible with the legacy `BoundField`) so existing form templates render unchanged.

## OpenAPI integration

Pass a Schema to `openapi.schema_body(SchemaClass)` for the request body, or use it as a return-type annotation for auto-generated 200 responses. Same declaration, two outputs (validation + docs).

Run `uv run plain docs schema` for full patterns. Run `uv run plain docs schema --api` for the public API surface.
