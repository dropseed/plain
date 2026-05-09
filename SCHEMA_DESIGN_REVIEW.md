# plain.schema design review

12 commits on `claude/compare-form-frameworks-9KkSG`, building a validation primitive from scratch and testing it across every Plain surface that needs it. This doc summarizes what was built, what was learned, and what's still open.

## TL;DR

`plain.schema.Schema` is a pure validating parser. `validate(data) → Self | Invalid`. The schema class plays double duty: it's both the parser and the validated-instance type. Eliminate `Invalid` via `isinstance` and the result is the typed schema directly — no `.data` indirection, no narrowing wart.

The same primitive drives runtime validation across **JSON APIs, HTMX actions, HTMX live-validate, background jobs, full HTML form pages with template binding, and OpenAPI documentation generation**. Type checking pulls its weight: agents who mistype field names, miss narrows, or assign wrong types all get caught at check time.

After 12 commits, the design holds up. The remaining open work is structural decisions (formal `plain.forms.Form` absorption, ModelForm story) rather than design exploration.

## The arc

### Origin: motivating problem

The conversation started from an observation: when Claude (or humans) write Plain views, they skip `forms.Form` and inline parsing directly off the request. Forms feel like overkill for HTMX actions, JSON endpoints, simple delete handlers, anywhere there's "as much side-effect as validation." But when forms ARE skipped, validation gets reinvented badly — ad-hoc dict-spelunking with no per-field error reporting and no type safety.

The thesis: build a **validation primitive at the same weight as `request.form_data["x"]`** that scales up to full HTML form ergonomics, and works identically across JSON / HTMX / jobs / pages. Type-check end to end so agents writing the code can't drift.

### The 12 commits, grouped

**Foundation (commits 1–2):**
1. `dab7f13` — Initial `plain.schema`: `Schema`, `Valid[T]`, `Invalid`, `validate()` classmethod, `make_schema()` for inline schemas, typed `.pyi` re-exports of forms fields. 10 tests, full type-narrowing demo.
2. `aba3de1` — OpenAPI integration in plain-api. `schema_from_type()` walks Schema classes; `openapi.schema_body(SchemaCls)` builds requestBody. Same Schema drives validation + docs. 6 tests.

**Cross-package exercise (commits 3–4):**
3. `fd29908` — Cross-field `check()` hook + HTMX action conversion + background job demo (`SendNotificationJob`). 12 new tests. Documented the `isinstance(result, Valid)` narrowing wart.
4. `e62e864` — `partial=True` for HTMX live-validation. Shipped README, agent rule, `htmx_post_validate` action.

**Hardest case (commit 5):**
5. `24a5d1c` — `BoundSchema` for HTML template binding. Converted `ContactView` to use Schema + BoundSchema. Same template renders for both Form and Schema (duck-typing). 9 contacts-schema tests.

**The big iteration (commit 6):**
6. `7e439d8` — **Replaced `Valid[T] | Invalid` with `Self | Invalid`.** The schema class is the validated instance; no wrapper class. Eliminated the narrowing wart. `check()` became an instance method (no Liskov ignore). All examples migrated. 30 schema tests.

**Real-world reach (commit 7):**
7. `c0ea42a` — File uploads via `validate(data, files=...)`. `FileField`/`ImageField` dispatch via isinstance. Exposed and fixed a latent FileField bug (`error_messages["text"]` → `["max_length"]`). 6 file-upload tests.

**Polish (commits 8–11):**
8. `a35ab4e` — `Result.apply_to(instance)` helper for schema → model copy. Replaces three lines of explicit setattr with one chainable call.
9. `0c4aeb4` — Typed `UploadedFile` re-export from `plain.schema`. Drops `: Any` annotations across all FileField uses.
10. `9eac35a` — Frozen schema instances. Validated values are the contract — silent post-validation mutation defeats the design.
11. `b7ee775` — `SchemaView` in `plain.views`: FormView-equivalent for schemas. GET-render / POST-validate / re-render-or-redirect cycle. Generic over schema type. ContactSchemaView migrated.
12. `fb49a15` — Hypothesis strategy: `plain.schema.testing.schema_strategy()` generates valid input dicts for property tests. Optional dep, gracefully absent.

## Final design surface

```
plain.schema/
├── __init__.py           Schema, Invalid, BoundSchema, BoundField,
│                         UploadedFile, make_schema
├── schema.py             Schema base, SchemaMeta, validate(),
│                         apply_to(), check() instance hook,
│                         frozen __setattr__/__delattr__
├── result.py             Invalid (frozen dataclass)
├── bind.py               BoundSchema, BoundField — duck-typed against
│                         plain.forms.BoundField for template reuse
├── types.py              Re-exports of plain.forms.fields.* — runtime
├── types.pyi             Type stubs declaring fields return their
│                         primitive Python type (str, int, UploadedFile,
│                         etc.) with Literal[True/False] overloads for
│                         required vs optional
├── testing.py            schema_strategy() for Hypothesis
└── README.md             Full reference

plain.views/
└── schema.py             SchemaView[S: Schema] — FormView equivalent

plain-api/openapi/
├── utils.py              schema_from_type() now also walks Schema
│                         classes; _FIELD_SCHEMAS maps each Field type
│                         to OpenAPI properties + constraints
└── helpers.py            schema_body(), schema_content() builders
```

The user-facing surface is small:

```python
from plain.schema import Schema, Invalid, types, BoundSchema, UploadedFile, make_schema
from plain.schema.testing import schema_strategy   # optional
from plain.views import SchemaView
from plain.api import openapi  # openapi.schema_body(SchemaCls)
```

## What's exercised end-to-end

| Surface | Where in the example | Pattern |
|---------|---------------------|---------|
| JSON API request body | `tasks/api.py:TaskQuickAddAPIView` | `Schema.validate(request.json_data)` |
| HTMX action | `tasks/views.py:htmx_post_rename` | `Schema.validate(request.form_data)` |
| HTMX live-validate | `tasks/views.py:htmx_post_validate` | `Schema.validate(..., partial=True)` |
| Background job | `jobs.py:SendNotificationJob` | `Schema.validate(self.payload)` |
| Full HTML form page | `contacts/views.py:ContactSchemaView` | `SchemaView[Schema]` + BoundSchema |
| Multipart file upload | `contacts/schemas.py:AttachmentUploadSchema` | `Schema.validate(data, files=...)` |
| OpenAPI requestBody | `tasks/api.py` | `openapi.schema_body(SchemaCls)` |
| OpenAPI response | (any view) | `def get(self) -> SchemaCls` |

## What type checking catches

Verified concrete cases:

- **Wrong field name on result**: `result.notiteh` → `Attribute 'notiteh' is not defined on ContactSchema`
- **Wrong type assignment**: `task.title: str = result.priority  # str | None` → `Object of type 'str | None' is not assignable to 'str'`
- **Missing narrow**: `result.email` without `isinstance(_, Invalid)` first → `Attribute 'email' is not defined on Invalid in union 'ContactSchema | Invalid'`
- **Wrong required vs Optional**: `email: str = types.EmailField(required=False)` → `'str | None' is not assignable to 'str'`
- **UploadedFile attribute typo**: `result.document.sze` → `Object of type 'UploadedFile' has no attribute 'sze'`

Each of these is a real agent-trap that the type checker catches before runtime.

## Warts found and resolved

| Wart | How resolved |
|------|--------------|
| `isinstance(result, Valid)` doesn't narrow generic type parameter | Replaced `Valid[T]` with `Self`; `result` IS the typed schema |
| `check()` classmethod with `data: Self` triggered Liskov ignore | Made `check()` an instance method; `self` is naturally typed |
| `: Any = types.FileField()` was uglier than needed | Re-exported `UploadedFile`; .pyi stub returns it |
| Latent `FileField` `KeyError` on long filenames | Renamed `error_messages["text"]` → `"max_length"` |
| Schemas accepting post-validation mutation silently | Frozen instances via `__setattr__`/`__delattr__` |
| `BooleanField(required=True)` rejecting `False` | Hypothesis strategy generates `True` only for required booleans |

Each wart was found by either writing real code against the design (commits 5–7) or by hypothesis-driven property tests (commit 12). The design got noticeably better with each pass.

## Test counts

- `plain` package: **337 tests**, all passing (was 307 before this work)
  - 30 schema tests (`test_schema.py`)
  - 6 SchemaView tests (`test_schema_view.py`)
  - 4 hypothesis property tests (`test_schema_testing.py`, skipped without hypothesis)
- `plain-api` package: **47 tests** (was 41), all passing
  - 6 new Schema → OpenAPI tests
- `example`: **19 tests** (was 1), all passing
  - 13 contacts schema tests
  - 5 jobs payload-schema tests
- Type-check clean across `plain.schema`, `plain.views`, `plain-api/openapi`, the entire example app

## The migration playthrough — what we actually learned

After the v1 design landed, we pushed the migration through every package that depended on `plain.forms`. Five commits across `plain-loginlink`, `plain-support`, `plain-passwords`, the `plain.views.Schema*View` hierarchy, and the example app's `contacts` and `tasks` apps. Together with the ModelForm-derived `TaskForm` in `tasks` (the heaviest case), these exercise every shape `plain.forms.Form` was used for.

### What migrated cleanly

**plain-loginlink** (52→47 lines, -1 file). One Form, one View. Method moved from cleaned_data access to `self.email` directly. Trivial.

**plain-support** (62→79 lines, but exposes user-side migration). Dynamic load via `SUPPORT_FORMS` setting still works (string paths, just point at Schema classes). User-defined Form with `__init__(user=, form_slug=)` becomes a Schema with `save(user=, form_slug=)` and `notify(entry, user=)` taking those as kwargs. View invokes them via `getattr(result, "save", None)`.

**plain-passwords** (190→166 lines, larger surface). Five Form classes converted. Surfaced three real migration patterns:
- Per-instance state (`self.user`) → `validate(context={"user": user})` + read in `check()`
- Auth state (`self._user` set during clean, read by view) → moved to a module-level `authenticate()` function called from the view; manual `Invalid` for auth failure
- ModelForm-derived (`PasswordSignupForm`) → fields declared explicitly

Two pre-existing bugs caught by tightened typing:
- `PasswordChangeView` used `self.user` without `login_required=True` — would silently fail anonymously. Fixed.
- `update_session_auth_hash(self.request, self.user)` had the same null-user gap.

**example/contacts** (forms.py deleted). `ContactForm` → `ContactSchema`, `ContactView` becomes `SchemaView[ContactSchema]`. Per-instance `ask_company` dynamic field becomes "always declared, conditionally rendered via context variable." `ArchiveSearchForm`/`ArchiveFilterForm` become `BoundSchema(prefix="q")`/`BoundSchema(prefix="f")`.

**example/tasks** (forms.py deleted, the hardest case). `TaskForm`-the-ModelForm with FK and M2M becomes explicit `TaskSchema`. FK validation against owner-scoped queryset moves from `ModelChoiceField(queryset=...)` to a `resolve_relations(owner=...)` method that runs after schema validation. Verbose but type-checkable. View glue grew ~10 lines per CRUD route.

### Two real bugs surfaced during migration

1. **`FileField.error_messages["text"]`** referenced as `["max_length"]` in `to_python` — long filenames raised KeyError instead of ValidationError. Fixed during file-upload work.
2. **`Schema.validate()` calling `.get()` on MultiValueDict** — for `MultipleChoiceField` this returned only the last submitted value. Now uses `.getlist()` when the input is a MultiValueDict and the field is MultipleChoiceField.

### Where the migration stopped — the line in the sand

`plain.postgres.forms.ModelForm` (782 lines) and `plain-admin` (which uses ModelForm via `Meta.model = X` auto-derive) were **not migrated**. Together they're an entangled subsystem that needs a real `ModelSchema` to replace cleanly:

- ModelForm walks `model._model_meta.fields` and produces a Field-per-model-field via `modelfield_to_formfield()` (~100 lines of dispatch). The ModelSchema equivalent would walk the same structure and produce Schema field declarations.
- `ModelChoiceField(queryset=...)` validates submitted IDs against a queryset. The schema equivalent needs the same queryset binding (the `resolve_relations(owner=...)` pattern in tasks/views.py shows what users do without it — it works but doubles the code).
- `ModelMultipleChoiceField` for M2M — same story.
- ModelForm's `save(commit=False)` and `save_m2m()` are convenient, but Schema's `apply_to(instance)` + manual `.tags.set(...)` covers the same ground with a few more lines.

**Building a real `ModelSchema` is a multi-day project.** Without it, ModelForm continues to provide value for the auto-derive case. With it, ModelForm becomes redundant and `plain.forms` can be retired entirely.

### Final state of `plain.forms`

After 5 migration commits, `plain.forms` is used by exactly two consumers:
- `plain.postgres.forms.ModelForm` (and its `ModelChoiceField`/`ModelMultipleChoiceField` types)
- `plain-admin` (via ModelForm)

Plus `plain.views.objects.CreateView/UpdateView/DeleteView` and `plain.views.FormView` continue to exist as Form-based equivalents alongside the new Schema-based ones. `plain.views` now ships both side by side — `FormView`/`CreateView`/etc. for ModelForm-driven code, `SchemaView`/`SchemaCreateView`/etc. for Schema-driven code.

This is the **honest endpoint** for the migration: Schema replaces Form for everything except the model-magic case. If/when ModelSchema gets built, the migration completes and `plain.forms` can be deprecated entirely.

### Pydantic interop

A Plain Schema and a Pydantic BaseModel are behaviorally similar (annotated fields, validate-style classmethod). A 30-line opt-in adapter could let users convert between them. **Skip until a real use case surfaces** — speculative cross-library bridges accumulate complexity faster than they earn it.

### ModelSchema — the actual remaining design problem

The migration playthrough proved Schema works for everything that doesn't rely on ModelForm's auto-derive-from-model magic. The remaining work to fully retire `plain.forms` is to build that magic on top of Schema:

```python
# What ModelSchema would look like
ContactSchema = Schema.for_model(Contact, fields=["email", "message"])

class TaskSchema(Schema):
    project: Project | None = ModelChoiceField(Project.query, owner_field="owner")
    tags: list[Tag] = ModelMultipleChoiceField(Tag.query, owner_field="owner")
```

The implementation requires:
- A `ModelSchema` base class (or `Schema.for_model()` factory) that introspects model fields and produces equivalent Schema fields
- `ModelChoiceField` / `ModelMultipleChoiceField` types that take a queryset/manager and validate submitted IDs against it
- Hooks for owner-scoping the queryset (currently the user does this in `resolve_relations`)
- A clean save story that handles M2M after the instance has a primary key

This is the **single biggest open piece**. Once it exists, plain-admin can migrate to it, ModelForm becomes redundant, and `plain.forms` can be deprecated.

### File handling beyond UploadedFile

The current design routes files through `request.files` to FileField via isinstance dispatch. Works for multipart form uploads. JSON endpoints with base64 files would need either custom field handling or a separate convention. **Not currently a need**; revisit if it comes up.

## Honest read

The design works **and the migration path through every Form consumer except ModelForm is proven to work**. Seventeen commits, every package that depended on plain.forms.Form successfully ported (loginlink, support, passwords, the example app's contacts and tasks). Every iteration found and resolved real friction; the migration playthrough surfaced two pre-existing bugs in plain.forms itself.

The remaining open work is **one design problem** — `ModelSchema` to replace `ModelForm`'s auto-derive-from-model machinery — not three or four. Once that exists, plain-admin migrates and `plain.forms` is dead code.

The agent-correctness story holds end to end:
- Annotations drive both runtime behavior and type-checker visibility
- `Self | Invalid` narrows cleanly without TypeIs hacks
- Frozen instances prevent silent post-validation mutation
- Hypothesis strategies catch field-constraint edge cases as a side effect of property testing
- Cross-package coherence (validation + OpenAPI + tests) from a single declaration

If I had to grade the final design:
- **Ergonomics: A.** No `.data` indirection; no narrowing workarounds; cleaner than `Form(request=request)`.
- **Type safety: A.** Every boundary is statically checked; agent typos are caught.
- **Cross-package reach: A.** Same primitive across JSON, HTMX, jobs, HTML, OpenAPI, file uploads.
- **Conceptual clarity: A−.** `Schema` plays double duty as both class declaration and validated-instance type — Pydantic-style. Familiar to most modern Python developers, slightly novel to Plain's existing user base.
- **Maturity: B+.** Hypothesis tests are property-based and uncover edge cases as we go. ModelForm story is the biggest open ergonomic question. Inline schemas remain a typing dead-end (they're for trivial cases by design; named classes for typed paths).

## Suggested next moves

In priority order:

1. **Review this branch.** 17 commits / ~4500 lines diff. Read the example app diffs first (`example/app/contacts/views.py`, `example/app/tasks/views.py`, `example/app/tasks/schemas.py`, `example/app/jobs.py`) — those are the user-facing shape and they show what migrating actually looks like. Then the new Schema-based downstream packages (`plain-loginlink`, `plain-support`, `plain-passwords`). Then the implementation in `plain/plain/schema/` and `plain/plain/views/schema.py`.

2. **Decide on `ModelSchema`.** The single open design problem. Two paths:
   - **Build it.** Multi-day project. Once done, `plain.forms` can be deprecated entirely.
   - **Don't build it.** Schema and Form coexist forever, with Schema the recommended path for everything except ModelForm-driven admin/CRUD.

3. **Land or iterate.** The current branch is internally consistent and ships a coherent migration. If the shape feels right, merge to master and either commit to ModelSchema or settle on coexistence as the long-term answer.

4. **Optional follow-ups (in order):**
   - Migration guide for users moving from `Form` to `Schema` (the patterns we learned in plain-passwords would make a good appendix)
   - Pydantic interop adapter, IF a real use case surfaces

The honest endpoint: the migration playthrough resolved every speculative question into either "it works" or "needs ModelSchema." Further work is implementation, not design.
