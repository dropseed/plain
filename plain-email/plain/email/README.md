# plain.email

**Send emails from your Plain application using SMTP, console output, or file-based backends.**

- [Overview](#overview)
    - [Sending a simple email](#sending-a-simple-email)
    - [Sending HTML emails](#sending-html-emails)
    - [Template-based emails](#template-based-emails)
    - [Attachments](#attachments)
- [Configuration](#configuration)
    - [SMTP settings](#smtp-settings)
- [Email backends](#email-backends)
    - [SMTP backend](#smtp-backend)
    - [Console backend](#console-backend)
    - [File-based backend](#file-based-backend)
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

The `TemplateEmail` class renders emails from template files. You provide a template name, and it looks for corresponding files in your `templates/email/` directory:

- `email/{template}.html` - HTML content (required)
- `email/{template}.txt` - Plain text content (optional, falls back to stripping HTML tags)
- `email/{template}.subject.txt` - Subject line (optional)

```python
from plain.email import TemplateEmail

email = TemplateEmail(
    template="welcome",
    context={"user_name": "Alice"},
    to=["alice@example.com"],
)
email.send()
```

With these template files:

```html
<!-- templates/email/welcome.html -->
<h1>Welcome, {{ user_name }}!</h1>
<p>We're glad you're here.</p>
```

```text
{# templates/email/welcome.subject.txt #}
Welcome to our app, {{ user_name }}!
```

You can subclass `TemplateEmail` to customize the template context by overriding `get_template_context()`.

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

## Configuration

Configure email settings in your `settings.py`:

```python
# settings.py

# Required: The backend to use for sending emails
EMAIL_BACKEND = "plain.email.backends.smtp.EmailBackend"

# Required: Default "From" address for outgoing emails
EMAIL_DEFAULT_FROM = "noreply@example.com"

# Optional: Default "Reply-To" addresses
EMAIL_DEFAULT_REPLY_TO = ["support@example.com"]
```

### SMTP settings

When using the SMTP backend, configure your mail server:

```python
# settings.py

EMAIL_HOST = "smtp.example.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "your-username"
EMAIL_HOST_PASSWORD = "your-password"
EMAIL_USE_TLS = True  # Use STARTTLS
EMAIL_USE_SSL = False  # Use implicit SSL (mutually exclusive with TLS)

# Optional settings
EMAIL_TIMEOUT = 10  # Connection timeout in seconds
EMAIL_SSL_CERTFILE = None  # Path to SSL certificate file
EMAIL_SSL_KEYFILE = None  # Path to SSL key file
EMAIL_USE_LOCALTIME = False  # Use local time in Date header (default: UTC)
```

## Email backends

The `EMAIL_BACKEND` setting controls how emails are sent. Plain includes three backends.

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

### File-based backend

Writes emails to files in a directory. Useful for testing and debugging.

```python
EMAIL_BACKEND = "plain.email.backends.filebased.EmailBackend"
EMAIL_FILE_PATH = "/path/to/email-output"
```

Each email is saved to a timestamped `.log` file in the specified directory.

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
