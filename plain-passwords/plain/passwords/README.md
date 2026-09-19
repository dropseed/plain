# plain.passwords

**Password hashing, validation, and authentication views for Plain.**

- [Overview](#overview)
- [HashedPassword](#hashedpassword)
- [Password hashing](#password-hashing)
- [Password validation](#password-validation)
- [Views](#views)
    - [Login](#login)
    - [Signup](#signup)
    - [Password change](#password-change)
    - [Password reset](#password-reset)
- [Forms](#forms)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

A password is stored as a [`HashedPassword`](./values.py#HashedPassword) — the encoded hash, never the raw string. Declare the column with `value_type=HashedPassword`:

```python
# app/users/models.py
from plain import postgres
from plain.postgres import Field, types
from plain.passwords.values import HashedPassword


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[HashedPassword] = types.TextField(value_type=HashedPassword)
```

Hash a raw password with `from_raw()`, and verify one with `check()`:

```python
user = User.query.create(
    email="user@example.com",
    password=HashedPassword.from_raw("my-secret-password"),
)

user.password.check("my-secret-password")  # True
```

For user authentication, you can use the built-in views. Add [`PasswordLoginView`](./views.py#PasswordLoginView) to your URLs:

```python
# app/urls.py
from plain.urls import path
from plain.passwords.views import PasswordLoginView

urlpatterns = [
    path("login/", PasswordLoginView, name="login"),
]
```

## HashedPassword

[`HashedPassword`](./values.py#HashedPassword) is the only form a password takes outside the form layer:

- `HashedPassword.from_raw(raw)` hashes a raw password with the configured hasher
- `password.check(raw)` tells you whether that raw password is the one behind the hash
- `password.needs_rehash()` tells you whether the hash is stale — a different algorithm than the first entry in `PASSWORD_HASHERS`, the same algorithm with different parameters, or a hash that can't be identified at all
- `str(password)` is the encoded hash, and `repr(password)` is deliberately opaque (`<HashedPassword>`) so a hash doesn't land in a log line or a traceback
- `==` compares two `HashedPassword`s in constant time

The column is a `value_type=` column (see [Value types](../../../plain-postgres/plain/postgres/README.md#value-types)), so the descriptor is strict and symmetric — `user.password` is a `HashedPassword`, and a `HashedPassword` is what you assign:

```python
from plain.passwords.values import HashedPassword

user.password = HashedPassword.from_raw("new-password")
user.update(fields=["password"])
```

Assigning a raw string is a type error at the call site and a `TypeError` at write time. Nothing hashes on save, and nothing inspects a value to guess whether it's hashed already:

```python
user.password = "new-password"
user.update()  # TypeError: ... takes a HashedPassword, not a str
```

The same refusal covers `User.query.update(password="new-password")` and `User.query.filter(password="new-password")`.

Two more things follow from this being an ordinary field declaration:

- **`password` is required in the typed constructor.** `User(email="user@example.com")` is a type error, rather than a `NOT NULL` failure at insert time.
- **The column is still `text`.** `value_type` never reaches a migration file, so no migration imports `HashedPassword`.

## Password hashing

Passwords are hashed using PBKDF2 with SHA256 by default. `HashedPassword` is the interface to it — [`hash_password`](./hashers.py#hash_password) and [`check_password`](./hashers.py#check_password) are the functions underneath, for the rare case where you hold an encoded hash on its own.

You can configure which hashers are available via the `PASSWORD_HASHERS` setting. The first hasher in the list is used for new passwords:

```python
# app/settings.py
PASSWORD_HASHERS = [
    "plain.passwords.hashers.PBKDF2PasswordHasher",
]
```

Hashes made by an older hasher keep working. Rehashing needs the raw password, so it happens right after a successful check — which is what [`check_user_password`](./core.py#check_user_password) does on every login:

```python
from plain.passwords.values import HashedPassword

if user.password.check(raw_password):
    if user.password.needs_rehash():
        user.password = HashedPassword.from_raw(raw_password)
        user.update(fields=["password"])
```

To create a custom hasher, subclass [`BasePasswordHasher`](./hashers.py#BasePasswordHasher) and implement the required methods.

## Password validation

[`validate_raw_password`](./validators.py#validate_raw_password) checks a raw password against the shipped rules. It raises a `ValidationError` collecting every rule that failed, each carrying its own `code`:

```python
from plain.exceptions import ValidationError
from plain.passwords.validators import validate_raw_password

try:
    validate_raw_password("password")
except ValidationError as error:
    print(error.messages)  # ['This password is too common.']
    print([e.code for e in error.error_list])  # ['password_too_common']
```

The rules it runs:

- [`MinimumLengthValidator`](./validators.py#MinimumLengthValidator) - At least 8 characters (`password_too_short`)
- [`CommonPasswordValidator`](./validators.py#CommonPasswordValidator) - Rejects a list of 20,000 common passwords (`password_too_common`)
- [`NumericPasswordValidator`](./validators.py#NumericPasswordValidator) - Rejects passwords that are entirely numeric (`password_entirely_numeric`)

This is the only place a raw password is inspected, and you rarely call it yourself: [`NewPasswordField`](./forms.py#NewPasswordField) calls it before hashing. Past that point a password is a `HashedPassword`, and there's nothing left to validate.

## Views

All views are designed to work with [plain.auth](../../../plain-auth/plain/auth/README.md) for session management.

### Login

[`PasswordLoginView`](./views.py#PasswordLoginView) handles email/password authentication:

```python
from plain.urls import path
from plain.passwords.views import PasswordLoginView

urlpatterns = [
    path("login/", PasswordLoginView, name="login"),
]
```

You can customize the success URL:

```python
class MyLoginView(PasswordLoginView):
    success_url = "/dashboard/"
```

### Signup

[`PasswordSignupView`](./views.py#PasswordSignupView) creates new users with email and password:

```python
from plain.urls import path
from plain.passwords.views import PasswordSignupView

urlpatterns = [
    path("signup/", PasswordSignupView, name="signup"),
]
```

### Password change

[`PasswordChangeView`](./views.py#PasswordChangeView) lets authenticated users change their password by entering their current password:

```python
from plain.urls import path
from plain.passwords.views import PasswordChangeView

urlpatterns = [
    path("password/change/", PasswordChangeView, name="password_change"),
]
```

### Password reset

Password reset requires two views and an email template. [`PasswordForgotView`](./views.py#PasswordForgotView) sends the reset email, and [`PasswordResetView`](./views.py#PasswordResetView) handles the token and new password:

```python
from plain.urls import path
from plain.passwords.views import PasswordForgotView, PasswordResetView


class MyPasswordForgotView(PasswordForgotView):
    reset_confirm_url_name = "password_reset"
    success_url = "/login/"


class MyPasswordResetView(PasswordResetView):
    success_url = "/login/"


urlpatterns = [
    path("password/forgot/", MyPasswordForgotView, name="password_forgot"),
    path("password/reset/", MyPasswordResetView, name="password_reset"),
]
```

You need to create a `password_reset` email template for [plain.email](../../../plain-email/plain/email/README.md). The template receives `email`, `user`, and `url` in its context.

## Forms

Several forms are available for building custom authentication flows:

- [`PasswordLoginForm`](./forms.py#PasswordLoginForm) - `email` and a raw `password` to check against the stored hash
- [`PasswordSignupForm`](./forms.py#PasswordSignupForm) - `email`, `password`, and `confirm_password`
- [`PasswordResetForm`](./forms.py#PasswordResetForm) - `email`, to request a reset link
- [`PasswordSetForm`](./forms.py#PasswordSetForm) - `new_password` and `confirm_password`, for setting a password without the old one
- [`PasswordChangeForm`](./forms.py#PasswordChangeForm) - `PasswordSetForm` plus `current_password`

The `password` and `new_password` fields are [`NewPasswordField`](./forms.py#NewPasswordField), which reads the raw string, runs `validate_raw_password()`, and cleans to a `HashedPassword`. So a validated form hands you a value the column accepts:

```python
from plain.passwords.core import set_user_password
from plain.passwords.forms import PasswordSetForm

# In a view's post()
result = self.validate_form(PasswordSetForm)
if isinstance(result, Response):
    return result
set_user_password(user, result.new_password)  # a HashedPassword
```

The `confirm_password` field stays a raw text field. Two hashes of the same password use different salts, so they can never be compared to each other — each form's `check()` compares the hashed field against the raw one with `HashedPassword.check()`.

## Settings

| Setting            | Default | Env var                         |
| ------------------ | ------- | ------------------------------- |
| `PASSWORD_HASHERS` | `[...]` | `PLAIN_PASSWORD_HASHERS` (JSON) |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I customize the login form?

Subclass [`PasswordLoginForm`](./forms.py#PasswordLoginForm) and set `form_class` on your view:

```python
from plain.passwords.forms import PasswordLoginForm
from plain.passwords.views import PasswordLoginView


class MyLoginForm(PasswordLoginForm):
    # Add custom fields or validation
    pass


class MyLoginView(PasswordLoginView):
    form_class = MyLoginForm
```

#### How do I customize password validation?

The three shipped rules are what `validate_raw_password()` runs, and there's no setting that swaps them out. Raw passwords only exist in the form layer, so that's where you change the rules: subclass [`NewPasswordField`](./forms.py#NewPasswordField), override `clean()`, and declare it on your own form.

```python
from typing import Any

from plain.exceptions import ValidationError
from plain.passwords.forms import NewPasswordField, PasswordSignupForm
from plain.passwords.values import HashedPassword


class NoSpacesPasswordField(NewPasswordField):
    def clean(self, value: Any) -> HashedPassword | None:
        raw = self.parse(value)
        if " " in raw:
            raise ValidationError(
                "Passwords can't contain spaces.", code="password_has_space"
            )
        return super().clean(value)  # runs the shipped rules, then hashes


class MySignupForm(PasswordSignupForm):
    password = NoSpacesPasswordField()
```

To replace the shipped rules instead of adding to them, don't call `super().clean()` — run your own checks on `raw` and return `HashedPassword.from_raw(raw)`.

#### How do I use a different hashing algorithm?

Add your hasher to `PASSWORD_HASHERS`. The first one is used for new passwords:

```python
PASSWORD_HASHERS = [
    "myapp.hashers.Argon2PasswordHasher",
    "plain.passwords.hashers.PBKDF2PasswordHasher",  # For existing passwords
]
```

#### How long are password reset tokens valid?

By default, tokens expire after 1 hour. Override `reset_token_max_age` on `PasswordResetView` to change this:

```python
class MyPasswordResetView(PasswordResetView):
    reset_token_max_age = 60 * 60 * 24  # 24 hours
```

## Installation

Install the package from PyPI:

```bash
uv add plain.passwords
```

Add the `password` field to your User model:

```python
# app/users/models.py
from plain import postgres
from plain.postgres import Field, types
from plain.passwords.values import HashedPassword


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[HashedPassword] = types.TextField(value_type=HashedPassword)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="unique_email"),
        ],
    )
```

Add login and logout views to your URLs:

```python
# app/urls.py
from plain.urls import path
from plain.auth.views import LogoutView
from plain.passwords.views import PasswordLoginView

urlpatterns = [
    path("login/", PasswordLoginView, name="login"),
    path("logout/", LogoutView, name="logout"),
]
```

Create templates for your views. The views don't ship any, so subclass one and point `template_name` at yours (`class LoginView(PasswordLoginView): template_name = "login.html"`).

Each view passes `form_class` and `form` to the template. Field values and errors are read through the `field_value`, `field_errors`, and `form_errors` helpers, and field metadata is on the field reference itself:

```html
{% extends "base.html" %}

{% block content %}
<form method="post">
    {% for error in form_errors(form) %}
    <p>{{ error.message }}</p>
    {% endfor %}

    <div>
        <label for="{{ form_class.email.html_id }}">Email</label>
        <input
            type="email"
            name="{{ form_class.email.name }}"
            id="{{ form_class.email.html_id }}"
            value="{{ field_value(form, form_class.email) }}"
            {% if form_class.email.required %}required{% endif %}>
        {% for error in field_errors(form, form_class.email) %}
        <p>{{ error.message }}</p>
        {% endfor %}
    </div>

    <div>
        <label for="{{ form_class.password.html_id }}">Password</label>
        <input
            type="password"
            name="{{ form_class.password.name }}"
            id="{{ form_class.password.html_id }}"
            {% if form_class.password.required %}required{% endif %}>
        {% for error in field_errors(form, form_class.password) %}
        <p>{{ error.message }}</p>
        {% endfor %}
    </div>

    <button type="submit">Log in</button>
</form>
{% endblock %}
```

For password resets, install [plain.email](../../../plain-email/plain/email/README.md) and create a reset email template.
