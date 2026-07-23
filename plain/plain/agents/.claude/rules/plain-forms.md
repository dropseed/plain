---
paths:
  - "**/forms.py"
  - "**/views.py"
---

# Forms

`plain.forms` is the headless validation layer — it parses and validates request data into Python, but renders no HTML. `plain.templates.views` provides the form-handling views.

## Declaring and validating

- `from plain import forms`; subclass `forms.Form` and declare fields as `forms.TextField()`, `forms.EmailField()`, `forms.IntegerField()`, etc.
- `required=False` makes a field optional.
- Instantiate with `MyForm(request=request)` (a `FormView` does this for you). `form.is_valid()` → bool; valid data lands in `form.cleaned_data`; errors in `form.errors`.
- Field-level checks → `clean_<field>()` (return the cleaned value, raise `forms.ValidationError` to reject).
- Cross-field checks → override `clean()`; attach errors with `self.add_error(field, ...)` (`field=None` for a form-level error read via `form.non_field_errors`).
- One form class validates both form-encoded and `application/json` bodies — Plain picks based on `Content-Type`.
- Multiple forms on one page → give each a `prefix=` so their field names don't collide.
- `ModelForm` lives in `plain.postgres` (`from plain.postgres.forms import ModelForm`) — run `uv run plain docs postgres --search ModelForm`.

## Views

- The generic views live in **`plain.templates.views`**, NOT `plain.views` — `from plain.templates.views import FormView, CreateView, UpdateView, DeleteView, ListView, DetailView, TemplateView`. (`plain.views` only has `View`, `RedirectView`, `ServerSentEventsView`.)
- `FormView`: set `form_class` and `success_url` (use `reverse_lazy(...)`). GET renders a blank form; POST validates and re-renders the bound form (in context as `form`) on failure.
- Parameterize for typed handlers: `class MyView(FormView[MyForm])` → `form_valid(self, form: MyForm)`.
- Side effects (send email, write rows) → override `form_valid(self, form)`, do the work, then `return super().form_valid(form)`.
- Inject constructor args or `initial` → override `get_form_kwargs()`.
- `CreateView`/`UpdateView` expect a `ModelForm`; `form_valid` calls `form.create()`/`form.update()`, sets `self.object`, and falls back to `self.object.get_absolute_url()` when `success_url` is unset.
- `UpdateView`/`DetailView` require `get_object()` (returning `None` or raising `DoesNotExist` → 404). `DeleteView` confirms with an empty form and deletes on POST. `ListView` requires `get_objects()`, exposed as `objects`.

## Templates

- Forms are headless — they render no HTML. Render inputs yourself from the `BoundField`: `form.email.html_name`, `.html_id`, `.value`, `.errors`, `.field.required`. Form-level errors via `form.non_field_errors`.

Run `uv run plain docs forms` for full field list and examples.
