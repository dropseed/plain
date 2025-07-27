# plain.passwords

**Password authentication for Plain.**

- [Overview](#overview)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

To enable password authentication in your Plain application, add the [`PasswordLoginView`](./views.py#PasswordLoginView) to your `urls.py`:

```python
# app/urls.py
from plain.urls import path
from plain.passwords.views import PasswordLoginView

urlpatterns = [
    path('login/', PasswordLoginView, name='login'),
    # ...
]
```

This sets up a basic login view where users can authenticate using their email and password.

For password resets to work, you also need to install [plain.email](https://github.com/dropseed/plain/tree/main/plain-email).

## FAQs

#### How do I customize the login form?

To customize the login form, you can subclass [`PasswordLoginForm`](./forms.py#PasswordLoginForm) and override its fields or methods as needed. Then, set the `form_class` attribute in your view to use your custom form.

```python
# app/forms.py
from plain.passwords.forms import PasswordLoginForm

class MyCustomLoginForm(PasswordLoginForm):
    # Add custom fields or override methods here
    pass

# app/views.py
from plain.passwords.views import PasswordLoginView
from .forms import MyCustomLoginForm

class MyPasswordLoginView(PasswordLoginView):
    form_class = MyCustomLoginForm
```

Update your `urls.py` to use your custom view:

```python
# app/urls.py
from plain.urls import path
from .views import MyPasswordLoginView

urlpatterns = [
    path('login/', MyPasswordLoginView, name='login'),
    # ...
]
```

## Installation

Install the `plain.passwords` package from [PyPI](https://pypi.org/project/plain.passwords/):

```bash
uv add plain.passwords
```
