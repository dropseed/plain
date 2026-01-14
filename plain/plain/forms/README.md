# Forms

**HTML form handling, validation, and data parsing.**

- [Overview](#overview)
- [Fields](#fields)
    - [Text fields](#text-fields)
    - [Numeric fields](#numeric-fields)
    - [Date and time fields](#date-and-time-fields)
    - [Choice fields](#choice-fields)
    - [File fields](#file-fields)
    - [Other fields](#other-fields)
- [Validation](#validation)
    - [Field-level validation](#field-level-validation)
    - [Form-level validation](#form-level-validation)
    - [Custom error messages](#custom-error-messages)
- [Rendering forms in templates](#rendering-forms-in-templates)
- [JSON data](#json-data)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can define a form by subclassing `Form` and declaring fields as class attributes. Each field handles parsing, validation, and type coercion for a specific input type.

```python
from plain import forms
from plain.views import FormView


class ContactForm(forms.Form):
    email = forms.EmailField()
    message = forms.CharField()


class ContactView(FormView):
    form_class = ContactForm
    template_name = "contact.html"

    def form_valid(self, form):
        # form.cleaned_data contains validated data
        email = form.cleaned_data["email"]
        message = form.cleaned_data["message"]
        # Do something with the data...
        return super().form_valid(form)
```

When the form is submitted, you access validated data through `form.cleaned_data`. Each field converts the raw input to an appropriate Python type (strings, integers, dates, etc.).

## Fields

All fields accept these common parameters:

- `required` - Whether the field is required (default: `True`)
- `initial` - Initial value for unbound forms
- `error_messages` - Dict of custom error messages
- `validators` - List of additional validator functions

### Text fields

**[`CharField`](./fields.py#CharField)** accepts text input with optional length constraints.

```python
name = forms.CharField(max_length=100, min_length=2)
bio = forms.CharField(required=False, strip=True)  # strip=True is the default
```

**[`EmailField`](./fields.py#EmailField)** validates email addresses.

```python
email = forms.EmailField()
```

**[`URLField`](./fields.py#URLField)** validates URLs and normalizes them (adds `http://` if missing).

```python
website = forms.URLField(required=False)
```

**[`RegexField`](./fields.py#RegexField)** validates against a regular expression.

```python
phone = forms.RegexField(regex=r"^\d{3}-\d{4}$")
```

### Numeric fields

**[`IntegerField`](./fields.py#IntegerField)** parses integers with optional min/max/step validation.

```python
age = forms.IntegerField(min_value=0, max_value=150)
quantity = forms.IntegerField(min_value=1, step_size=1)
```

**[`FloatField`](./fields.py#FloatField)** parses floating-point numbers.

```python
price = forms.FloatField(min_value=0)
```

**[`DecimalField`](./fields.py#DecimalField)** parses `Decimal` values with precision control.

```python
amount = forms.DecimalField(max_digits=10, decimal_places=2)
```

### Date and time fields

**[`DateField`](./fields.py#DateField)** parses dates in various formats (e.g., `2024-01-15`, `01/15/2024`).

```python
birthday = forms.DateField()
```

**[`TimeField`](./fields.py#TimeField)** parses times (e.g., `14:30`, `14:30:59`).

```python
start_time = forms.TimeField()
```

**[`DateTimeField`](./fields.py#DateTimeField)** parses combined date and time values.

```python
scheduled_at = forms.DateTimeField()
```

**[`DurationField`](./fields.py#DurationField)** parses time durations into `timedelta` objects.

```python
duration = forms.DurationField()  # e.g., "1 day, 2:30:00"
```

### Choice fields

**[`ChoiceField`](./fields.py#ChoiceField)** validates against a list of choices.

```python
PRIORITY_CHOICES = [
    ("low", "Low"),
    ("medium", "Medium"),
    ("high", "High"),
]
priority = forms.ChoiceField(choices=PRIORITY_CHOICES)
```

You can also use Python enums directly.

```python
from enum import Enum

class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

priority = forms.ChoiceField(choices=Priority)
```

**[`TypedChoiceField`](./fields.py#TypedChoiceField)** coerces the value to a specific type after validation.

```python
year = forms.TypedChoiceField(
    choices=[(str(y), str(y)) for y in range(2020, 2030)],
    coerce=int,
)
```

**[`MultipleChoiceField`](./fields.py#MultipleChoiceField)** allows selecting multiple options.

```python
tags = forms.MultipleChoiceField(choices=[("a", "A"), ("b", "B"), ("c", "C")])
```

### File fields

**[`FileField`](./fields.py#FileField)** handles file uploads.

```python
document = forms.FileField(max_length=255)  # max_length applies to filename
```

**[`ImageField`](./fields.py#ImageField)** validates that the upload is a valid image (requires Pillow).

```python
avatar = forms.ImageField(required=False)
```

### Other fields

**[`BooleanField`](./fields.py#BooleanField)** parses boolean values (handles HTML checkbox behavior).

```python
subscribe = forms.BooleanField(required=False)  # unchecked = False
terms = forms.BooleanField()  # must be checked
```

**[`NullBooleanField`](./fields.py#NullBooleanField)** allows `True`, `False`, or `None`.

```python
preference = forms.NullBooleanField()
```

**[`UUIDField`](./fields.py#UUIDField)** parses UUID strings into `uuid.UUID` objects.

```python
token = forms.UUIDField()
```

**[`JSONField`](./fields.py#JSONField)** parses and validates JSON strings.

```python
config = forms.JSONField()
metadata = forms.JSONField(indent=2, sort_keys=True)  # for display formatting
```

## Validation

### Field-level validation

You can add custom validation for a specific field by defining a `clean_<fieldname>` method. This runs after the field's built-in validation.

```python
class SignupForm(forms.Form):
    username = forms.CharField(max_length=30)
    email = forms.EmailField()

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username.lower() in ["admin", "root", "system"]:
            raise forms.ValidationError("This username is reserved.")
        return username.lower()  # Return the cleaned value
```

### Form-level validation

Override the `clean()` method for validation that involves multiple fields.

```python
class PasswordForm(forms.Form):
    password = forms.CharField()
    password_confirm = forms.CharField()

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm = cleaned_data.get("password_confirm")

        if password and confirm and password != confirm:
            raise forms.ValidationError("Passwords do not match.")

        return cleaned_data
```

Errors raised in `clean()` are stored in `form.non_field_errors` since they are not associated with a specific field.

### Custom error messages

You can customize error messages per field.

```python
email = forms.EmailField(
    error_messages={
        "required": "We need your email address.",
        "invalid": "Please enter a valid email.",
    }
)
```

## Rendering forms in templates

Forms provide access to field data through [`BoundField`](./boundfield.py#BoundField) objects. You render the HTML inputs yourself, giving you full control over markup and styling.

```html
<form method="post">
    <!-- Non-field errors (from form.clean()) -->
    {% for error in form.non_field_errors %}
    <div class="error">{{ error }}</div>
    {% endfor %}

    <div>
        <label for="{{ form.email.html_id }}">Email</label>
        <input
            type="email"
            name="{{ form.email.html_name }}"
            id="{{ form.email.html_id }}"
            value="{{ form.email.value }}"
            {% if form.email.field.required %}required{% endif %}>

        {% for error in form.email.errors %}
        <div class="field-error">{{ error }}</div>
        {% endfor %}
    </div>

    <div>
        <label for="{{ form.message.html_id }}">Message</label>
        <textarea
            name="{{ form.message.html_name }}"
            id="{{ form.message.html_id }}"
            {% if form.message.field.required %}required{% endif %}>{{ form.message.value }}</textarea>

        {% for error in form.message.errors %}
        <div class="field-error">{{ error }}</div>
        {% endfor %}
    </div>

    <button type="submit">Send</button>
</form>
```

Each bound field provides:

- `html_name` - The input's `name` attribute
- `html_id` - The input's `id` attribute
- `value` - The current value (initial or submitted)
- `errors` - List of validation error messages
- `field` - The underlying [`Field`](./fields.py#Field) instance
- `initial` - The field's initial value

For large applications, you can reduce repetition by creating reusable patterns with Jinja [includes](https://jinja.palletsprojects.com/en/stable/templates/#include), [macros](https://jinja.palletsprojects.com/en/stable/templates/#macros), or [plain.elements](/plain-elements/README.md).

## JSON data

Forms automatically handle JSON request bodies when the `Content-Type` header is `application/json`. The same form class works for both HTML form submissions and JSON API requests.

```python
class ApiForm(forms.Form):
    name = forms.CharField()
    count = forms.IntegerField()
```

For HTML form data:

```
POST /submit
Content-Type: application/x-www-form-urlencoded

name=Example&count=42
```

For JSON data:

```
POST /submit
Content-Type: application/json

{"name": "Example", "count": 42}
```

Both will validate the same way and populate `cleaned_data` with the same values.

## FAQs

#### How do I make a field optional?

Set `required=False` on the field.

```python
notes = forms.CharField(required=False)
```

#### How do I pre-populate a form with existing data?

Pass an `initial` dict when creating the form in your view.

```python
form = ContactForm(request=request, initial={"email": user.email})
```

#### How do I access the raw submitted data?

Use `form.data` to access the raw data dict before validation.

```python
if form.is_bound:
    raw_email = form.data.get("email")
```

#### How do I add custom validators to a field?

Pass a list of validator functions to the `validators` parameter.

```python
from plain.validators import MinLengthValidator

username = forms.CharField(validators=[MinLengthValidator(3)])
```

#### Why is my checkbox field always `False`?

HTML checkboxes don't submit any value when unchecked. `BooleanField` handles this by returning `False` when the field is missing from form data. Make sure you use `required=False` if the checkbox is optional.

#### How do I handle multiple forms on one page?

Use the `prefix` parameter to namespace each form's fields.

```python
contact_form = ContactForm(request=request, prefix="contact")
signup_form = SignupForm(request=request, prefix="signup")
```

This prefixes field names like `contact-email` and `signup-email`.

## Installation

Add `plain.forms` to your `INSTALLED_PACKAGES` in `app/settings.py`.

```python
INSTALLED_PACKAGES = [
    # ...
    "plain.forms",
]
```

Create a form class in your app.

```python
# app/forms.py
from plain import forms


class ContactForm(forms.Form):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    message = forms.CharField()
```

Use the form with a view. The [`FormView`](/plain-views/README.md) base class handles GET/POST logic automatically.

```python
# app/views.py
from plain.views import FormView

from .forms import ContactForm


class ContactView(FormView):
    form_class = ContactForm
    template_name = "contact.html"

    def form_valid(self, form):
        # Process the validated data
        name = form.cleaned_data["name"]
        email = form.cleaned_data["email"]
        message = form.cleaned_data["message"]
        # Send email, save to database, etc.
        return super().form_valid(form)
```

Create the template to render the form.

```html
<!-- app/templates/contact.html -->
{% extends "base.html" %}

{% block content %}
<h1>Contact Us</h1>

<form method="post">
    {% for error in form.non_field_errors %}
    <div class="error">{{ error }}</div>
    {% endfor %}

    <div>
        <label for="{{ form.name.html_id }}">Name</label>
        <input
            type="text"
            name="{{ form.name.html_name }}"
            id="{{ form.name.html_id }}"
            value="{{ form.name.value }}"
            required>
        {% for error in form.name.errors %}
        <div class="field-error">{{ error }}</div>
        {% endfor %}
    </div>

    <div>
        <label for="{{ form.email.html_id }}">Email</label>
        <input
            type="email"
            name="{{ form.email.html_name }}"
            id="{{ form.email.html_id }}"
            value="{{ form.email.value }}"
            required>
        {% for error in form.email.errors %}
        <div class="field-error">{{ error }}</div>
        {% endfor %}
    </div>

    <div>
        <label for="{{ form.message.html_id }}">Message</label>
        <textarea
            name="{{ form.message.html_name }}"
            id="{{ form.message.html_id }}"
            required>{{ form.message.value }}</textarea>
        {% for error in form.message.errors %}
        <div class="field-error">{{ error }}</div>
        {% endfor %}
    </div>

    <button type="submit">Send Message</button>
</form>
{% endblock %}
```
