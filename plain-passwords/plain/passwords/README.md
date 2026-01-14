# plain.passwords

**Password hashing, validation, and authentication views for Plain.**

- [Overview](#overview)
- [Password hashing](#password-hashing)
- [Password validation](#password-validation)
- [PasswordField](#passwordfield)
- [Views](#views)
    - [Login](#login)
    - [Signup](#signup)
    - [Password change](#password-change)
    - [Password reset](#password-reset)
- [Forms](#forms)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can hash and verify passwords using the `hash_password` and `check_password` functions:

```python
from plain.passwords.hashers import hash_password, check_password

# Hash a password for storage
hashed = hash_password("my-secret-password")
# Returns something like: pbkdf2_sha256$720000$abc123...$xyz789...

# Verify a password against a hash
is_valid = check_password("my-secret-password", hashed)
# Returns True
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

## Password hashing

Passwords are hashed using PBKDF2 with SHA256 by default. The [`hash_password`](./hashers.py#hash_password) function generates a secure hash:

```python
from plain.passwords.hashers import hash_password

hashed = hash_password("user-password")
```

The [`check_password`](./hashers.py#check_password) function verifies a password against a stored hash. It also handles automatic hash upgrades when the hashing algorithm changes:

```python
from plain.passwords.hashers import check_password

def setter(new_hash):
    # Called when the hash needs to be upgraded
    user.password = new_hash
    user.save()

is_valid = check_password("user-password", stored_hash, setter=setter)
```

You can configure which hashers are available via the `PASSWORD_HASHERS` setting. The first hasher in the list is used for new passwords:

```python
# app/settings.py
PASSWORD_HASHERS = [
    "plain.passwords.hashers.PBKDF2PasswordHasher",
]
```

To create a custom hasher, subclass [`BasePasswordHasher`](./hashers.py#BasePasswordHasher) and implement the required methods.

## Password validation

Three validators are included for checking password strength:

- [`MinimumLengthValidator`](./validators.py#MinimumLengthValidator) - Ensures passwords meet a minimum length (default: 8 characters)
- [`CommonPasswordValidator`](./validators.py#CommonPasswordValidator) - Rejects passwords from a list of 20,000 common passwords
- [`NumericPasswordValidator`](./validators.py#NumericPasswordValidator) - Rejects passwords that are entirely numeric

```python
from plain.passwords.validators import (
    MinimumLengthValidator,
    CommonPasswordValidator,
    NumericPasswordValidator,
)
from plain.exceptions import ValidationError

validators = [
    MinimumLengthValidator(min_length=10),
    CommonPasswordValidator(),
    NumericPasswordValidator(),
]

password = "test"
for validator in validators:
    try:
        validator(password)
    except ValidationError as e:
        print(e.message)
```

## PasswordField

[`PasswordField`](./models.py#PasswordField) is a model field that automatically hashes passwords before saving. It includes all three validators by default:

```python
from plain import models
from plain.passwords.models import PasswordField

@models.register_model
class User(models.Model):
    email = models.EmailField(unique=True)
    password = PasswordField()
```

When you assign a raw password, it gets hashed automatically on save:

```python
user = User(email="user@example.com", password="my-password")
user.save()
# user.password is now a hash like: pbkdf2_sha256$720000$...
```

For better type checking support, you can import from `plain.passwords.types`:

```python
from plain.passwords.types import PasswordField
```

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

- [`PasswordLoginForm`](./forms.py#PasswordLoginForm) - Email and password login
- [`PasswordSignupForm`](./forms.py#PasswordSignupForm) - User registration with password confirmation
- [`PasswordSetForm`](./forms.py#PasswordSetForm) - Set a new password without the old one
- [`PasswordChangeForm`](./forms.py#PasswordChangeForm) - Change password with current password verification
- [`PasswordResetForm`](./forms.py#PasswordResetForm) - Request a password reset email

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

Pass custom validators to `PasswordField`:

```python
from plain.passwords.models import PasswordField
from plain.passwords.validators import MinimumLengthValidator

password = PasswordField(validators=[
    MinimumLengthValidator(min_length=12),
])
```

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
# app/models.py
from plain import models
from plain.passwords.models import PasswordField

@models.register_model
class User(models.Model):
    email = models.EmailField(unique=True)
    password = PasswordField()
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

Create templates for your views. For the login view, create `templates/passwords/passwordlogin.html`:

```html
{% extends "base.html" %}

{% block content %}
<form method="post">
    {{ csrf_input }}
    {{ form.as_elements }}
    <button type="submit">Log in</button>
</form>
{% endblock %}
```

For password resets, install [plain.email](../../../plain-email/plain/email/README.md) and create a reset email template.
