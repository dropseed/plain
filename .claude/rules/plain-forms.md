---
paths:
  - "**/forms.py"
  - "**/views.py"
---

# Forms

`plain.forms` is a validating parser — an untrusted dict in, typed Python data out. It does not render HTML or take a request.

## Declaring and validating

- Subclass `Form`; declare each field with a `types.*` constructor (`email = types.EmailField()`). No annotations needed — `types.*` is typed.
- `required=False` makes the cleaned value optional (`Field[T | None]`).
- `MyForm.validate(data)` returns `MyForm | Invalid` — it never raises on bad input.
- Branch with `if not result:` — a `Form` is truthy, `Invalid` is falsy. Past the guard, `result` is the typed form (`result.email` is `str`).
- `Invalid.errors` is one flat `list[Error]`; `Error(message, code, field)` — `field=None` is a form-level error. `Invalid.raw` keeps the input.
- Cross-field rules → override `check()`, return `list[Error] | None`. Don't raise.
- Validation needing the current user, or any state the form doesn't carry, goes in the view. (A `ModelForm` is the exception that already knows the database — see below.)
- `DateTimeField` cleans to an **aware** datetime: a naive submission is read as local wall time in the current timezone.

## Views

- No `FormView`/`CreateView`/`UpdateView`/`DeleteView` — write explicit `get`/`post` on a `TemplateView`.
- `self.validate_form(MyForm)` is the one-liner for "validate from `request.form_data`, re-render on failure, otherwise return the typed instance." Add `instance=obj` when editing an existing row with a `ModelForm`.
- `self.render_form(MyForm, result)` passes `form_class` and `form` to the template. `result=None` is a blank render; pass `values=` to pre-fill it.
- There is no `errors=` argument. For a failure the form itself can't see — an authentication rejection after `validate()` succeeded — build the result and pass it as `result`:

    ```python
    return self.render_form(
        LoginForm,
        Invalid(
            errors=[Error("Incorrect email or password.", code="invalid_login")],
            raw=self.request.form_data,
        ),
    )
    ```

- Side effects (send email, create related rows) → a function the view calls after `validate()` succeeds.
- An `APIView` can `return` an `Invalid` directly — it renders as the standard JSON error body with a 400.

## Templates

- The view passes `form_class` (the `Form` subclass) and `form` (a `Form | Invalid`). The template reads each field through:
    - `field_value(form, form_class.email)` — typed display value (`T | None`)
    - `field_errors(form, form_class.email)` — `list[Error]` for that field
    - `form_errors(form)` — form-level errors (those not attached to a field)
- Field metadata lives on the `Field` reference itself — `form_class.email.required`, `.choices`, `.html_id`, `.name`. No helper needed.
- An `Error` renders via `error.message`.

## Model-backed forms

- `ModelForm` lives in `plain.postgres` (`from plain.postgres.forms import ModelForm, model_field`). Declare each field `name = model_field(Model.column)` — no `model =`, no annotation. `MyForm.model()` reports the model those columns came from.
- `validate()` also pre-checks the model's constraints, so a duplicate comes back as an `Invalid` rather than blowing up at write time. Editing an existing row takes `instance=` so the row doesn't collide with itself.
- `ModelForm` never writes. Persist a validated result with the `plain.postgres.forms` functions: `create_from(Model, result, **extra)` inserts, `update_from(instance, result)` updates.

## Differences from Django

The rebuilt API has no equivalent for these — don't reach for them:

- `is_valid()` / `cleaned_data` → `validate()` returns the typed form or `Invalid`; read `result.<field>` directly.
- `clean_<field>()` → the field's own validators, or a `types.*` field with the constraint on it.
- `clean()` / `add_error()` / `non_field_errors` → `check()`, returning `list[Error]` with `field=None` for form-level ones.
- `BoundField` / `form.fields[...]` / `form[name]` → the `field_value` / `field_errors` helpers plus the `Field` reference for metadata.
- `prefix` → give the two forms distinct field names, or validate whichever one was submitted.
- `error_messages` → the message is on the `ValidationError` a field raises; match on `Error.code`, not wording.
- `ModelForm.Meta` (`model`, `fields`, `exclude`) → one `model_field(Model.column)` per field.
- `ModelForm.save()` / `save(commit=False)` → `create_from()` / `update_from()`.
- Forms never render HTML — no widgets, no `{{ form.as_p }}`, no `form.media`.

Run `uv run plain docs forms` for full patterns and the field list.
