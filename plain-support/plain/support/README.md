# plain.support

**Provides support forms for your application.**

- [Overview](#overview)
- [Configuration](#configuration)
    - [Settings](#settings)
    - [Custom forms](#custom-forms)
- [Views](#views)
    - [Embedded forms](#embedded-forms)
- [Security considerations](#security-considerations)
- [Installation](#installation)

## Overview

Include the support URLs in your `urls.py`:

```python
# app/urls.py
from plain.urls import include, path
import plain.support.urls

urlpatterns = [
    path("support/", include(plain.support.urls)),
    # ...
]
```

Configure the required settings:

```python
# app/settings.py
SUPPORT_EMAIL = "support@example.com"
```

This will create a support form at `/support/` that users can fill out. When submitted, an email will be sent to your `SUPPORT_EMAIL` address with the user's message.

## Configuration

### Settings

- `SUPPORT_EMAIL` (required): The email address where support requests will be sent
- `SUPPORT_FORMS`: A dictionary mapping form slugs to form classes (defaults to `{"default": "plain.support.forms.SupportForm"}`)

### Custom forms

You can create custom support forms by extending [`SupportForm`](./forms.py#SupportForm):

```python
# app/forms.py
from plain.support.forms import SupportForm
from plain import models

class BugReportForm(SupportForm):
    browser = models.CharField(max_length=100, required=False)

    class Meta:
        model = SupportFormEntry
        fields = ["name", "email", "message", "browser"]
```

Then register it in your settings:

```python
SUPPORT_FORMS = {
    "default": "plain.support.forms.SupportForm",
    "bug-report": "app.forms.BugReportForm",
}
```

The form will be available at `/support/bug-report/`.

## Views

The package provides several views:

- [`SupportFormView`](./views.py#SupportFormView): Renders the support form on a full page
- [`SupportIFrameView`](./views.py#SupportIFrameView): Renders the form in an iframe-friendly format (CSRF-exempt)
- [`SupportFormJSView`](./views.py#SupportFormJSView): Serves JavaScript for embedded forms

### Embedded forms

Support forms can be embedded in other sites using an iframe:

```html
<iframe src="https://example.com/support/iframe/" width="100%" height="600"></iframe>
```

Or using the provided JavaScript embed:

```html
<div id="support-form"></div>
<script src="https://example.com/support/form.js"></script>
```

## Security considerations

Most support forms allow users to type in any email address. Be careful, because anybody can pretend to be anybody else at this point. Conversations either need to continue over email (which confirms they have access to the email account), or include a verification step (emailing a code to the email address, for example).

The [`SupportForm.find_user()`](./forms.py#SupportForm) method attempts to associate entries with existing users by email, but this does not confirm the submitter's identity.

## Installation

Install the `plain.support` package from [PyPI](https://pypi.org/project/plain.support/):

```bash
uv add plain.support
```
