# plain.password

Password authentication for Plain.

## Usage

To enable password authentication in your Plain application, add the `PasswordLoginView` to your `urls.py`:

```python
# app/urls.py
from plain.urls import path
from plain.passwords.views import PasswordLoginView

urlpatterns = [
    path('login/', PasswordLoginView.as_view(), name='login'),
    # ...
]
```

This sets up a basic login view where users can authenticate using their username and password.

## FAQs

### How do I customize the login form?

To customize the login form, you can subclass `PasswordLoginForm` and override its fields or methods as needed. Then, set the `form_class` attribute in your `PasswordLoginView` to use your custom form.

```python
# app/forms.py
from plain.passwords.forms import PasswordLoginForm

class MyCustomLoginForm(PasswordLoginForm):
    # Add custom fields or override methods here
    pass
```

```python
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
    path('login/', MyPasswordLoginView.as_view(), name='login'),
    # ...
]
```
