# plain.loginlink

**Passwordless authentication using email login links.**

- [Overview](#overview)
- [How it works](#how-it-works)
- [Customizing the login form](#customizing-the-login-form)
- [Customizing the email](#customizing-the-email)
- [Customizing link expiration](#customizing-link-expiration)
- [Generating links manually](#generating-links-manually)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Login links let users authenticate by clicking a link sent to their email address, instead of entering a password. This approach is often called "magic links" and provides a simple, secure authentication experience.

When a user enters their email address, they receive an email with a one-time login link. Clicking the link logs them in automatically. The links are cryptographically signed and include an expiration time for security.

```python
# app/urls.py
from plain.urls import Router, path, include

from plain.loginlink.urls import LoginlinkRouter
from plain.loginlink.views import LoginLinkFormView


class AppRouter(Router):
    namespace = "app"
    urls = [
        path("login/", LoginLinkFormView, name="login"),
        include("loginlink/", LoginlinkRouter),
    ]
```

With this configuration, users visit `/login/` to enter their email, then receive a link that directs them to `/loginlink/token/<token>/` to complete authentication.

## How it works

The login flow has three steps:

1. User submits their email address via [`LoginLinkFormView`](./views.py#LoginLinkFormView)
2. If the email matches a user, a signed login link is emailed to them
3. User clicks the link, which validates the token and logs them in

The token includes both the user ID and email address. This means links become invalid if the user's email changes or if the account is deleted, providing an extra layer of security.

Three error states are handled automatically:

- **Expired** - The link has passed its expiration time
- **Invalid** - The signature doesn't match (tampered or corrupted)
- **Changed** - The user's email has changed since the link was generated

## Customizing the login form

You can customize the login form by subclassing [`LoginLinkFormView`](./views.py#LoginLinkFormView):

```python
from plain.loginlink.views import LoginLinkFormView


class CustomLoginView(LoginLinkFormView):
    template_name = "login.html"
    success_url = "/check-your-email/"
```

The form includes a hidden `next` field that preserves the redirect destination after login. You can pre-populate this by adding `?next=/dashboard/` to the login URL.

## Customizing the email

The default email template is minimal. You can override it by creating your own templates.

Create `templates/email/loginlink.html`:

```html
<p>Hi {{ user.email }},</p>
<p>Click here to log in: <a href="{{ url }}">{{ url }}</a></p>
<p>This link expires in {{ expires_in|floatformat:0 }} seconds.</p>
```

Create `templates/email/loginlink.subject.txt`:

```
Log in to My App
```

For more control over how the email is sent, subclass [`LoginLinkForm`](./forms.py#LoginLinkForm) and override the [`get_template_email`](./forms.py#get_template_email) method:

```python
from plain.loginlink.forms import LoginLinkForm
from plain.email import TemplateEmail


class CustomLoginLinkForm(LoginLinkForm):
    def get_template_email(self, *, email, context):
        return TemplateEmail(
            template="custom_login",
            to=[email],
            context=context,
        )
```

See [plain.email](/plain-email/plain/email/README.md) for more details on email templates.

## Customizing link expiration

By default, login links expire after 1 hour (3600 seconds). You can change this by overriding the form's `maybe_send_link` call:

```python
from plain.loginlink.views import LoginLinkFormView
from plain.loginlink.forms import LoginLinkForm


class CustomLoginLinkForm(LoginLinkForm):
    def maybe_send_link(self, request, expires_in=60 * 15):  # 15 minutes
        return super().maybe_send_link(request, expires_in=expires_in)


class CustomLoginView(LoginLinkFormView):
    form_class = CustomLoginLinkForm
```

## Generating links manually

You can generate login links programmatically using [`generate_link_url`](./links.py#generate_link_url):

```python
from plain.loginlink.links import generate_link_url


def send_welcome_email(request, user):
    login_url = generate_link_url(
        request=request,
        user=user,
        email=user.email,
        expires_in=60 * 60 * 24,  # 24 hours
    )
    # Use login_url in your custom email...
```

To validate a token manually, use [`get_link_token_user`](./links.py#get_link_token_user):

```python
from plain.loginlink.links import (
    get_link_token_user,
    LoginLinkExpired,
    LoginLinkInvalid,
    LoginLinkChanged,
)


def validate_token(token):
    try:
        user = get_link_token_user(token)
        return user
    except LoginLinkExpired:
        print("Link has expired")
    except LoginLinkInvalid:
        print("Link is invalid")
    except LoginLinkChanged:
        print("User email has changed")
    return None
```

## FAQs

#### What happens if the email doesn't match any user?

The form still redirects to the "sent" page without revealing whether the email exists. This prevents account enumeration attacks.

#### Can I use this alongside password authentication?

Yes. You can offer both options on your login page and let users choose their preferred method.

#### How are the tokens signed?

Tokens use Plain's cryptographic signing with the `SECRET_KEY` setting. The [`ExpiringSigner`](./signing.py#ExpiringSigner) embeds the expiration timestamp directly in the signed value rather than checking it on unsign.

#### What if a user is already logged in when they click a link?

The [`LoginLinkLoginView`](./views.py#LoginLinkLoginView) logs out the current user first, then logs in the user from the token. This ensures the link always authenticates the intended user.

## Installation

Install the `plain.loginlink` package from [PyPI](https://pypi.org/project/plain.loginlink/):

```console
uv add plain.loginlink
```

This package requires [plain.auth](/plain-auth/plain/auth/README.md) and [plain.email](/plain-email/plain/email/README.md) to be configured.

Add the loginlink views to your URL configuration:

```python
# app/urls.py
from plain.urls import Router, path, include

from plain.loginlink.urls import LoginlinkRouter
from plain.loginlink.views import LoginLinkFormView


class AppRouter(Router):
    namespace = "app"
    urls = [
        path("login/", LoginLinkFormView, name="login"),
        include("loginlink/", LoginlinkRouter),
    ]
```

Set `AUTH_LOGIN_URL` in your settings to point to your login view:

```python
# app/settings.py
AUTH_LOGIN_URL = "app:login"
```

Create the "sent" and "failed" templates. These templates should extend your base template.

Create `templates/loginlink/sent.html`:

```html
{% extends "base.html" %}

{% block content %}
<h1>Check your email</h1>
<p>If your email address was found, we sent you a link to log in.</p>
<p>If you don't see it, check your spam folder.</p>
{% endblock %}
```

Create `templates/loginlink/failed.html`:

```html
{% extends "base.html" %}

{% block content %}
{% if error == "expired" %}
<h1>Link Expired</h1>
{% elif error == "invalid" %}
<h1>Link Invalid</h1>
{% elif error == "changed" %}
<h1>Link Changed</h1>
{% else %}
<h1>Link Error</h1>
{% endif %}

<a href="{{ login_url }}">Request a new link</a>
{% endblock %}
```

Create a login form template. Create `templates/loginlink/loginlinkform.html` (or set a custom `template_name` on your view):

```html
{% extends "base.html" %}

{% block content %}
<h1>Log in</h1>
<form method="post">
    {{ csrf_input }}
    {{ form.email.as_input }}
    <input type="hidden" name="next" value="{{ request.query_params.next }}">
    <button type="submit">Send login link</button>
</form>
{% endblock %}
```

Your passwordless login is now ready. Visit `/login/` to test the flow.
