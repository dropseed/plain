# plain.email

**Send emails from your Plain application using SMTP, console output, or the development preview backend.**

- [Overview](#overview)
    - [Sending a simple email](#sending-a-simple-email)
    - [Sending HTML emails](#sending-html-emails)
    - [Template-based emails](#template-based-emails)
    - [Attachments](#attachments)
- [Settings](#settings)
- [Email backends](#email-backends)
    - [SMTP backend](#smtp-backend)
    - [Console backend](#console-backend)
    - [Preview backend](#preview-backend)
    - [In-memory backend](#in-memory-backend)
- [Testing](#testing)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can send emails using the `send_mail` function for simple cases, or use the `EmailMessage` and `EmailMultiAlternatives` classes for more control. For template-based emails, the `TemplateEmail` class renders HTML templates automatically.

### Sending a simple email

The `send_mail` function is the easiest way to send an email.

```python
from plain.email import send_mail

send_mail(
    subject="Welcome!",
    message="Thanks for signing up.",
    from_email="hello@example.com",
    recipient_list=["user@example.com"],
)
```

To include an HTML version along with the plain text:

```python
send_mail(
    subject="Welcome!",
    message="Thanks for signing up.",
    from_email="hello@example.com",
    recipient_list=["user@example.com"],
    html_message="<h1>Thanks for signing up!</h1>",
)
```

### Sending HTML emails

For more control over multipart emails, use `EmailMultiAlternatives`.

```python
from plain.email import EmailMultiAlternatives

email = EmailMultiAlternatives(
    subject="Your order confirmation",
    body="Your order #123 has been confirmed.",
    from_email="orders@example.com",
    to=["customer@example.com"],
)
email.attach_alternative("<h1>Order #123 Confirmed</h1>", "text/html")
email.send()
```

### Template-based emails

The `TemplateEmail` class renders emails from templates in your `templates/email/` directory. You provide a template name, and it renders `email/{template}.html` as the HTML body. The subject is passed directly as a `subject=` argument.

```python
from plain.email import TemplateEmail

email = TemplateEmail(
    template="welcome",
    subject="Welcome to our app",
    context={"user_name": "Alice"},
    to=["alice@example.com"],
)
email.send()
```

With this template file:

```html
<!-- templates/email/welcome.html -->
<h1>Welcome, {{ user_name }}!</h1>
<p>We're glad you're here.</p>
```

For the plain-text body, add an optional `email/{template}.txt`. It renders through plain.html text mode — `{{ }}` interpolation works, but the content is treated as plain text (no HTML parsing or escaping):

```
{# templates/email/welcome.txt #}
Welcome, {{ user_name }}!

We're glad you're here.
```

When no `.txt` file exists, the plain-text body falls back to a tag-stripped version of the HTML.

You can subclass `TemplateEmail` to customize the template context by overriding `get_template_context()`, or to take full control of the plain-text body by overriding `render_plain()`.

### Attachments

You can attach files to any email message.

```python
from plain.email import EmailMessage

email = EmailMessage(
    subject="Your report",
    body="Please find your report attached.",
    to=["user@example.com"],
)

# Attach content directly
email.attach("report.csv", csv_content, "text/csv")

# Or attach a file from disk
email.attach_file("/path/to/report.pdf")

email.send()
```

## Settings

| Setting                  | Default       | Env var                        |
| ------------------------ | ------------- | ------------------------------ |
| `EMAIL_BACKEND`          | Required      | `PLAIN_EMAIL_BACKEND`          |
| `EMAIL_DEFAULT_FROM`     | Required      | `PLAIN_EMAIL_DEFAULT_FROM`     |
| `EMAIL_DEFAULT_REPLY_TO` | `None`        | `PLAIN_EMAIL_DEFAULT_REPLY_TO` |
| `EMAIL_HOST`             | `"localhost"` | `PLAIN_EMAIL_HOST`             |
| `EMAIL_PORT`             | `587`         | `PLAIN_EMAIL_PORT`             |
| `EMAIL_HOST_USER`        | `""`          | `PLAIN_EMAIL_HOST_USER`        |
| `EMAIL_HOST_PASSWORD`    | `""`          | `PLAIN_EMAIL_HOST_PASSWORD`    |
| `EMAIL_USE_TLS`          | `True`        | `PLAIN_EMAIL_USE_TLS`          |
| `EMAIL_USE_SSL`          | `False`       | `PLAIN_EMAIL_USE_SSL`          |
| `EMAIL_TIMEOUT`          | `None`        | `PLAIN_EMAIL_TIMEOUT`          |
| `EMAIL_SSL_CERTFILE`     | `None`        | `PLAIN_EMAIL_SSL_CERTFILE`     |
| `EMAIL_SSL_KEYFILE`      | `None`        | `PLAIN_EMAIL_SSL_KEYFILE`      |
| `EMAIL_USE_LOCALTIME`    | `False`       | `PLAIN_EMAIL_USE_LOCALTIME`    |

See [`default_settings.py`](./default_settings.py) for more details.

## Email backends

The `EMAIL_BACKEND` setting controls how emails are sent. Plain includes four backends.

### SMTP backend

The default backend sends emails via SMTP.

```python
EMAIL_BACKEND = "plain.email.backends.smtp.EmailBackend"
```

### Console backend

Prints emails to the console instead of sending them. Useful during development.

```python
EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"
```

### Preview backend

Captures each sent message as a `.eml` file in `.plain/emails/` for inspection during development. Nothing is delivered to an SMTP server.

```python
EMAIL_BACKEND = "plain.email.backends.preview.EmailBackend"
```

Or via env var: `PLAIN_EMAIL_BACKEND=plain.email.backends.preview.EmailBackend`.

When [`plain.toolbar`](../../plain-toolbar/plain/toolbar/README.md) is installed, the toolbar gains an **Email** panel that lists recent captured messages and renders their HTML bodies inline. You can also open any `.eml` file directly in Mail.app.

### In-memory backend

Captures sent messages in a list instead of delivering them — intended for tests. See [Testing](#testing) for the `mailoutbox` fixture built on it.

```python
EMAIL_BACKEND = "plain.email.backends.locmem.EmailBackend"
```

## Testing

`plain.email` ships a `mailoutbox` pytest fixture. It routes email to the in-memory backend for the duration of a test and yields the captured messages:

```python
from plain.email import send_mail


def test_sends_email(mailoutbox):
    send_mail("Subject", "Body", "from@example.com", ["person@example.com"])

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["person@example.com"]
```

The fixture clears the outbox around each test (so messages never leak between tests) and restores the original `EMAIL_BACKEND` afterward. It registers automatically — no pytest plugin configuration needed.

## FAQs

#### How do I send to multiple recipients efficiently?

Use `send_mass_mail` to send multiple messages over a single connection:

```python
from plain.email import send_mass_mail

messages = (
    ("Subject 1", "Body 1", "from@example.com", ["to1@example.com"]),
    ("Subject 2", "Body 2", "from@example.com", ["to2@example.com"]),
)
send_mass_mail(messages)
```

#### How do I reuse a connection for multiple emails?

Use the backend as a context manager:

```python
from plain.email import get_connection, EmailMessage

with get_connection() as connection:
    for user in users:
        email = EmailMessage(
            subject="Hello",
            body="Hi there!",
            to=[user.email],
            connection=connection,
        )
        email.send()
```

#### How do I add custom headers?

Pass a `headers` dict to any email class:

```python
email = EmailMessage(
    subject="Hello",
    body="Content",
    to=["user@example.com"],
    headers={"X-Custom-Header": "value", "Reply-To": "reply@example.com"},
)
```

#### How do I create a custom email backend?

Subclass [`BaseEmailBackend`](./backends/base.py#BaseEmailBackend) and implement the `send_messages` method:

```python
from plain.email.backends.base import BaseEmailBackend

class MyBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        # Your sending logic here
        return len(email_messages)
```

## Installation

Install the `plain.email` package from PyPI:

```bash
uv add plain.email
```

Add `plain.email` to your `INSTALLED_PACKAGES` and configure the required settings:

```python
# settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.email",
]

EMAIL_BACKEND = "plain.email.backends.smtp.EmailBackend"
EMAIL_DEFAULT_FROM = "noreply@example.com"

# For SMTP (adjust for your mail provider)
EMAIL_HOST = "smtp.example.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "your-username"
EMAIL_HOST_PASSWORD = "your-password"
EMAIL_USE_TLS = True
```

For local development, use the console backend to see emails in your terminal:

```python
EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"
```
