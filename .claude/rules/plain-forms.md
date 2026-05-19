---
paths:
  - "**/forms.py"
  - "**/views.py"
---

# Forms

`plain.forms` is a pure validating parser — an untrusted dict in, typed Python data out. It does not render HTML, take a request, or touch a database.

## Declaring and validating

- Subclass `Form`; declare each field with a `types.*` constructor (`email = types.EmailField()`). No annotations needed — `types.*` is typed.
- `required=False` makes the cleaned value optional (`Field[T | None]`).
- `MyForm.validate(data)` returns `MyForm | Invalid` — it never raises on bad input.
- Branch with `if not result:` — a `Form` is truthy, `Invalid` is falsy. Past the guard, `result` is the typed form (`result.email` is `str`).
- `Invalid.errors` is one flat `list[Error]`; `Error(message, code, field)` — `field=None` is a form-level error. `Invalid.raw` keeps the input.
- Cross-field rules → override `check()`, return `list[Error] | None`. Don't raise.
- Validation needing the DB or current user goes in the view, not the form.

## Views

- No `FormView`/`CreateView`/`UpdateView`/`DeleteView` — write explicit `get`/`post` on a `TemplateView`.
- GET renders `FormDisplay(MyForm)`; POST calls `validate()`, then re-renders `FormDisplay(MyForm, result)` on failure.
- Side effects (send email, create related rows) → a function the view calls after `validate()` succeeds.

## Templates

- The view passes a `FormDisplay`. Read `form.<field>.value` / `.errors` / `.required` / `.choices` / `.html_id` / `.name`, `form.errors` for form-level errors, `{% for field in form %}` to iterate. An `Error` renders via `error.message`.

## Model-backed forms

- `ModelForm` lives in `plain.postgres` (`from plain.postgres.forms import ModelForm, model_field`). Declare each field `name = model_field(Model.column)` — no `model =`, no annotation.
- `ModelForm` never writes. Persist a validated result with the `plain.postgres.forms` functions: `create_from(Model, result, **extra)` inserts, `update_from(instance, result)` updates.

## Removed in the rebuild — don't use

- `is_valid()`, `cleaned_data`, `clean_<field>()`, `clean()`, `non_field_errors`, `BoundField`, `form.fields[...]`, `prefix`, `error_messages`, `Form.apply_to()`, `ModelForm.save()`.

Run `uv run plain docs forms` for full patterns and the field list.
