# Forms

**Validating parsers that turn untrusted input into typed Python data.**

- [Overview](#overview)
- [Validation](#validation)
    - [The result is a typed form or `Invalid`](#the-result-is-a-typed-form-or-invalid)
    - [Cross-field validation with `check()`](#cross-field-validation-with-check)
    - [Where validation lives](#where-validation-lives)
- [Fields](#fields)
    - [Text fields](#text-fields)
    - [Numeric fields](#numeric-fields)
    - [Date and time fields](#date-and-time-fields)
    - [Choice fields](#choice-fields)
    - [File fields](#file-fields)
    - [Other fields](#other-fields)
- [Rendering forms in templates](#rendering-forms-in-templates)
- [JSON and other input](#json-and-other-input)
- [Model-backed forms](#model-backed-forms)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

A form is a typed schema. You subclass `Form` and declare each field with a `types.*` constructor:

```python
from plain.forms import Form, types


class ContactForm(Form):
    email = types.EmailField()
    message = types.TextField(max_length=2000)
```

`ContactForm.validate(data)` turns a dict of untrusted input into either a typed `ContactForm` instance or an `Invalid`:

```python
result = ContactForm.validate(request.form_data)
if not result:
    ...                  # result is Invalid — handle the errors
result.email             # str — every field cleaned and typed
result.message           # str
```

`validate()` **never raises** on bad input. A `Form` instance is truthy and `Invalid` is falsy, so `if not result:` branches to the failure case and otherwise leaves you the validated instance directly — no `cleaned_data` dict, no `.is_valid()` call.

A form is pure data. It doesn't take a request, render HTML, or touch a database — so the same form validates an HTML submission, a JSON body, a job payload, or a dict in a test.

## Validation

### The result is a typed form or `Invalid`

`validate()` returns a tagged union — a `Form` subclass instance on success, an [`Invalid`](./result.py#Invalid) on failure:

```python
result = ContactForm.validate(data)
if not result:
    for error in result.errors:
        print(error.field, error.code, error.message)
    print(result.raw)        # the original submitted input
```

`Invalid.errors` is one flat list of [`Error`](./result.py#Error). Each `Error` carries:

- `message` — human-readable text
- `code` — a stable machine identifier (`"required"`, `"invalid"`, `"max_length"`, …) — match on this in tests and handlers, not the wording
- `field` — the field name, or `None` for a form-level error

`Invalid.raw` keeps the original input, which is what re-rendering a rejected form reads from.

A returned instance means _every_ field validated, so `result.<field>` is always safe — there is no half-populated form.

### Cross-field validation with `check()`

A field validates its own shape. For a rule that spans fields, override `check()` — it runs after every field has cleaned, with `self` as the typed instance, and returns a list of `Error`s (or `None`):

```python
from plain.forms import Error, Form, types


class SignupForm(Form):
    password = types.TextField()
    password_confirm = types.TextField()

    def check(self):
        if self.password != self.password_confirm:
            return [Error("Passwords do not match.", code="mismatch", field="password_confirm")]
        return None
```

Set each `Error`'s `field` to the field it concerns, or leave it `None` for a form-level error. Return — don't raise.

### Where validation lives

The form validates _shape_. Everything else lives elsewhere:

- **Cross-field rules over the form's own fields** → `check()`.
- **Validation needing external state** (the current user, a database uniqueness check) → the view, or a function the view calls — not the form.
- **Side effects** (send an email, create related rows) → a function the view calls after `validate()` succeeds.
- **Persisting a model** → a validated [`ModelForm`](#model-backed-forms) feeds `create_from()` / `update_from()` from `plain.postgres.forms`.

## Fields

Every field accepts `required` (default `True`) and `initial`. A field declared `required=False` cleans to `None` when absent, and its type reflects that — `types.IntegerField(required=False)` makes `result.count` an `int | None`.

### Text fields

**[`TextField`](./fields.py#TextField)** accepts text input with optional length constraints.

```python
name = types.TextField(max_length=100, min_length=2)
bio = types.TextField(required=False, strip=False)  # strip defaults to True
```

**[`EmailField`](./fields.py#EmailField)** validates email addresses. **[`URLField`](./fields.py#URLField)** validates URLs.

```python
email = types.EmailField()
website = types.URLField(required=False)
```

**[`RegexField`](./fields.py#RegexField)** validates against a regular expression.

```python
phone = types.RegexField(r"^\d{3}-\d{4}$")
```

### Numeric fields

**[`IntegerField`](./fields.py#IntegerField)** and **[`FloatField`](./fields.py#FloatField)** parse numbers with optional `min_value`, `max_value`, and `step_size`.

```python
age = types.IntegerField(min_value=0, max_value=150)
price = types.FloatField(min_value=0)
```

**[`DecimalField`](./fields.py#DecimalField)** parses `Decimal` values with precision control.

```python
amount = types.DecimalField(max_digits=10, decimal_places=2)
```

### Date and time fields

**[`DateField`](./fields.py#DateField)**, **[`TimeField`](./fields.py#TimeField)**, and **[`DateTimeField`](./fields.py#DateTimeField)** parse dates and times into the matching `datetime` objects. **[`DurationField`](./fields.py#DurationField)** parses a duration into a `timedelta`.

```python
birthday = types.DateField()
scheduled_at = types.DateTimeField()
duration = types.DurationField()
```

### Choice fields

**[`ChoiceField`](./fields.py#ChoiceField)** validates against a list of `(value, label)` choices.

```python
PRIORITY_CHOICES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
priority = types.ChoiceField(choices=PRIORITY_CHOICES)
```

A Python `Enum` works as `choices` too. **[`TypedChoiceField`](./fields.py#TypedChoiceField)** coerces the validated value with a `coerce` callable, and **[`MultipleChoiceField`](./fields.py#MultipleChoiceField)** cleans to a `list`.

```python
year = types.TypedChoiceField(choices=[(str(y), str(y)) for y in range(2020, 2030)], coerce=int)
tags = types.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])
```

### File fields

**[`FileField`](./fields.py#FileField)** handles uploads; **[`ImageField`](./fields.py#ImageField)** also checks the upload is a valid image (requires Pillow). Pass uploads to `validate()` as `files=` — see [JSON and other input](#json-and-other-input).

```python
document = types.FileField(max_length=255)  # max_length applies to the filename
avatar = types.ImageField(required=False)
```

### Other fields

**[`BooleanField`](./fields.py#BooleanField)** parses HTML checkbox values. **[`NullBooleanField`](./fields.py#NullBooleanField)** allows `True`, `False`, or `None`. **[`UUIDField`](./fields.py#UUIDField)** parses UUID strings, and **[`JSONField`](./fields.py#JSONField)** parses JSON.

```python
subscribe = types.BooleanField(required=False)  # unchecked = False
token = types.UUIDField()
config = types.JSONField()
```

## Rendering forms in templates

The core types — `Form`, `validate`, `Invalid` — carry no rendering interface. To render a form, a view passes the `form_class` and the `Form | Invalid` result to the template; the template reads each field through the `field_value`, `field_errors`, and `form_errors` helpers from `plain.forms`.

The view is explicit `get`/`post`:

```python
from plain.http import RedirectResponse
from plain.templates.views import TemplateView


class ContactView(TemplateView):
    template_name = "contact.html"

    def get(self):
        return self.render_form(ContactForm)

    def post(self):
        result = ContactForm.validate(self.request.form_data)
        if not result:
            # re-render with the submitted values and their errors
            return self.render_form(ContactForm, result)
        send_contact_email(result.email, result.message)
        return RedirectResponse("/thanks/")
```

`self.render_form(form_class, result=None, *, values=None, errors=None, **context)` passes both `form_class` and `form` into the template context. Three modes:

```python
self.render_form(ContactForm)                              # blank — shows each field's initial
self.render_form(ContactForm, result)                      # a failed validate() — values + errors
self.render_form(ContactForm, values={"email": user.email})  # pre-filled
```

In the template, helpers take `form` (the result) plus a field reference (`form_class.email`). Field metadata is on the field reference itself — `form_class.email.required`, `.choices`, `.html_id`, `.name`:

```html
<form method="post">
    {% for error in form_errors(form) %}
    <div class="error">{{ error.message }}</div>
    {% endfor %}

    <label for="{{ form_class.email.html_id }}">Email</label>
    <input
        type="email"
        name="{{ form_class.email.name }}"
        id="{{ form_class.email.html_id }}"
        value="{{ field_value(form, form_class.email) }}"
        {% if form_class.email.required %}required{% endif %}>
    {% for error in field_errors(form, form_class.email) %}
    <div class="field-error">{{ error.message }}</div>
    {% endfor %}

    <button type="submit">Send</button>
</form>
```

`{% for name, field in form_class.fields().items() %}` iterates every declared field. For large apps, reduce repetition with Jinja [macros](https://jinja.palletsprojects.com/en/stable/templates/#macros) or [plain.elements](/plain-elements/README.md).

The helpers are typed through the field reference — `field_value(form, ContactForm.email)` narrows to `str | None`, `field_value(form, ContactForm.age)` to `int | None`, and so on. Python's type system can't dispatch attribute lookup by literal name, so the function-call shape is what carries the type through.

## JSON and other input

`validate()` takes any dict, so one form class serves an HTML page and a JSON API:

```python
ContactForm.validate(request.form_data)                  # an HTML form POST
ContactForm.validate(request.json_data)                  # a JSON request body
ContactForm.validate(payload)                            # a job argument, a test
ContactForm.validate(request.form_data, files=request.files)  # with file uploads
```

An `Invalid` is already structured for JSON — each `Error` carries a `field`, `code`, and `message`, so a JSON view skips the template helpers entirely. Serialize `result.errors` straight into the response:

```python
from dataclasses import asdict

from plain.http import JsonResponse


def post(self):
    result = ContactForm.validate(self.request.json_data)
    if not result:
        return JsonResponse({"errors": [asdict(e) for e in result.errors]}, status_code=400)
    send_contact_email(result.email, result.message)
    return JsonResponse({"ok": True})
```

The response body then looks like:

```json
{
    "errors": [
        {"message": "Enter a valid email address.", "code": "invalid", "field": "email"}
    ]
}
```

The stable `code` is what a JSON client branches on — the `message` is for display, the `field` pairs the error with its input, and a form-level error has `"field": null`.

## Model-backed forms

When a form's fields mirror a database model, use `ModelForm` — it lives in [`plain.postgres`](../../../plain-postgres/plain/postgres/README.md) because it depends on the ORM. Declare each field with `model_field(Model.column)`; its type and validation are copied from that column, so `result.title` is typed exactly as `Note.title` and a column typo is a type error:

```python
from plain.postgres.forms import ModelForm, model_field


class NoteForm(ModelForm):
    title = model_field(Note.title)
    body = model_field(Note.body)
```

`NoteForm` validates like any form — `ModelForm` itself never writes. To persist a validated result, pass it to the `create_from()` / `update_from()` functions in `plain.postgres.forms`: `create_from(Note, result)` inserts a new row — pass any columns the form doesn't carry as keyword arguments, e.g. `create_from(Note, result, author=user)` — and `update_from(note, result)` writes it onto an existing row.

## FAQs

#### How do I make a field optional?

Set `required=False`. The cleaned value becomes `None` when the field is absent, and the type reflects it.

```python
notes = types.TextField(required=False)   # result.notes is str | None
```

#### How do I pre-populate a form?

Pass a `values` dict to `render_form`:

```python
self.render_form(ContactForm, values={"email": user.email})
```

For a blank form, `self.render_form(ContactForm)` already shows each field's `initial` value.

#### How do I access the raw submitted data?

`Invalid.raw` holds the original input that was passed to `validate()`.

#### Why is my checkbox always `False`?

An HTML checkbox submits nothing when unchecked. `BooleanField` returns `False` for a missing value — declare it `required=False` so an unchecked box is allowed.

#### How do I put two forms on one page?

Give them distinct field names, or use two separate `Form` classes. Validate whichever one the request submitted.

#### How do I run validation that needs the database or current user?

Not in the form — a form is a pure parser. Do it in the view (or a function the view calls) after `validate()` succeeds. See [Where validation lives](#where-validation-lives).

## Installation

`plain.forms` is part of Plain core — there's nothing to add to `INSTALLED_PACKAGES`. Import it directly:

```python
# app/forms.py
from plain.forms import Form, types


class ContactForm(Form):
    name = types.TextField(max_length=100)
    email = types.EmailField()
    message = types.TextField()
```

Wire it to a view with explicit `get`/`post`:

```python
# app/views.py
from plain.http import RedirectResponse
from plain.templates.views import TemplateView

from .forms import ContactForm


class ContactView(TemplateView):
    template_name = "contact.html"

    def get(self):
        return self.render_form(ContactForm)

    def post(self):
        result = ContactForm.validate(self.request.form_data)
        if not result:
            return self.render_form(ContactForm, result)
        # result is the typed ContactForm — do the work, then redirect
        return RedirectResponse("/thanks/")
```

And render it (see [Rendering forms in templates](#rendering-forms-in-templates) for the full field markup):

```html
<!-- app/templates/contact.html -->
{% extends "base.html" %}

{% block content %}
<form method="post">
    {% for error in form_errors(form) %}
    <div class="error">{{ error.message }}</div>
    {% endfor %}

    <label for="{{ form_class.email.html_id }}">Email</label>
    <input
        type="email"
        name="{{ form_class.email.name }}"
        id="{{ form_class.email.html_id }}"
        value="{{ field_value(form, form_class.email) }}">
    {% for error in field_errors(form, form_class.email) %}
    <div class="field-error">{{ error.message }}</div>
    {% endfor %}

    <button type="submit">Send</button>
</form>
{% endblock %}
```
