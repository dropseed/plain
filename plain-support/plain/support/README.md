# plain.support

**Provides support forms for your application.**

- [Overview](#overview)
- [Settings](#settings)
- [Custom forms](#custom-forms)
- [Views](#views)
    - [Embedded forms](#embedded-forms)
- [Security considerations](#security-considerations)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can add support forms to your application to collect user feedback, bug reports, and other messages. When a form is submitted, an email is sent to your support team.

```python
# app/urls.py
from plain.urls import include, path, Router
from plain.support.urls import SupportRouter


class AppRouter(Router):
    namespace = "app"
    urls = [
        path("support/", include(SupportRouter)),
        # ...
    ]
```

```python
# app/settings.py
SUPPORT_EMAIL = "support@example.com"
```

This creates a support form at `/support/form/default/` that users can fill out. When submitted, an email is sent to your `SUPPORT_EMAIL` address with the user's name, email, and message.

## Settings

| Setting         | Default              | Env var               |
| --------------- | -------------------- | --------------------- |
| `SUPPORT_EMAIL` | Required             | `PLAIN_SUPPORT_EMAIL` |
| `SUPPORT_FORMS` | `{"default": "..."}` | -                     |

See [`default_settings.py`](./default_settings.py) for more details.

## Custom forms

You can create custom support forms by extending [`SupportForm`](./forms.py#SupportForm). The form uses [ModelForm](/plain/plain/models/README.md#modelform) from `plain.models.forms`.

```python
# app/forms.py
from plain.support.forms import SupportForm
from plain.support.models import SupportFormEntry
from plain import forms


class BugReportForm(SupportForm):
    browser = forms.CharField(max_length=100, required=False)

    class Meta:
        model = SupportFormEntry
        fields = ["name", "email", "message", "browser"]
```

Then register it in your settings:

```python
# app/settings.py
SUPPORT_FORMS = {
    "default": "plain.support.forms.SupportForm",
    "bug-report": "app.forms.BugReportForm",
}
```

The form will be available at `/support/form/bug-report/`.

You can also customize the email notification by overriding the [`notify`](./forms.py#SupportForm) method:

```python
class BugReportForm(SupportForm):
    # ...

    def notify(self, instance):
        # Send to a different channel, create a ticket, etc.
        pass
```

## Views

You can use the following views for different scenarios:

- [`SupportFormView`](./views.py#SupportFormView): Renders the support form on a full page
- [`SupportIFrameView`](./views.py#SupportIFrameView): Renders the form in an iframe-friendly format
- [`SupportFormJSView`](./views.py#SupportFormJSView): Serves JavaScript for embedded forms

### Embedded forms

Support forms can be embedded in other sites using an iframe:

```html
<iframe src="https://example.com/support/form/default/iframe/" width="100%" height="600"></iframe>
```

Or using the provided JavaScript embed:

```html
<div id="support-form"></div>
<script src="https://example.com/support/form/default.js"></script>
```

## Security considerations

Most support forms allow users to type in any email address. Be careful, because anybody can pretend to be anybody else. Conversations either need to continue over email (which confirms they have access to the email account), or include a verification step (emailing a code to the email address, for example).

The [`SupportForm.find_user()`](./forms.py#SupportForm) method attempts to associate entries with existing users by email, but this does not confirm the submitter's identity.

## FAQs

#### How do I customize the form templates?

You can override the default templates by creating your own templates at:

- `support/page.html`: The full page template
- `support/iframe.html`: The iframe-friendly template
- `support/forms/<form_slug>.html`: The form rendering template
- `support/success/<form_slug>.html`: The success message template

#### How do I view support form entries?

Support form entries are stored in the [`SupportFormEntry`](./models.py#SupportFormEntry) model. You can query them directly or use the admin interface if you have `plain.admin` installed with the [`SupportFormEntryAdmin`](./admin.py#SupportFormEntryAdmin) registered.

#### Can I associate support entries with logged-in users?

Yes. When a user is logged in, the form automatically associates the entry with their account. If the user is not logged in (common with iframe embeds), the form will try to find an existing user by email address using `find_user()`.

## Installation

Install the `plain.support` package from [PyPI](https://pypi.org/project/plain.support/):

```bash
uv add plain.support
```

Add `plain.support` to your `INSTALLED_PACKAGES` in `app/settings.py`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.support",
]
```

Set the required `SUPPORT_EMAIL` setting:

```python
# app/settings.py
SUPPORT_EMAIL = "support@example.com"
```

Include the support URLs in your app's URL configuration:

```python
# app/urls.py
from plain.urls import include, path, Router
from plain.support.urls import SupportRouter


class AppRouter(Router):
    namespace = "app"
    urls = [
        path("support/", include(SupportRouter)),
        # ...
    ]
```

Run migrations to create the `SupportFormEntry` table:

```bash
uv run plain migrate
```

Create the required templates. At minimum, you need a form template:

```html
<!-- app/templates/support/forms/default.html -->
{{ form.as_fields }}
<button type="submit">Send message</button>
```

And a success template:

```html
<!-- app/templates/support/success/default.html -->
<p>Thank you for your message! We'll get back to you soon.</p>
```

You also need to create an email template for notifications. See the [plain.email](/plain/plain/email/README.md) package for template setup instructions:

```html
<!-- app/emails/support_form_entry.html -->
<p>New support request from {{ support_form_entry.name }} ({{ support_form_entry.email }})</p>
<p>{{ support_form_entry.message }}</p>
```

Visit `/support/form/default/` to see your support form.
