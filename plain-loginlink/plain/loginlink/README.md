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

When a user enters their email address, they receive an email with a login link. Clicking the link logs them in automatically. The links are cryptographically signed and carry an embedded expiration, and they keep working until that expiration passes.

```python
# app/urls.py
from plain.urls import Router, path, include

from plain.loginlink.urls import LoginlinkRouter
from plain.loginlink.views import LoginLinkFormView


class AppRouter(Router):
    namespace = "app"
    urls = (
        path("login/", LoginLinkFormView, name="login"),
        include("loginlink/", LoginlinkRouter),
    )
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

By default, login links expire after 1 hour (3600 seconds). Change it by setting [`link_expires_in`](./forms.py#LoginLinkForm) on the form:

```python
from plain.loginlink.views import LoginLinkFormView
from plain.loginlink.forms import LoginLinkForm


class CustomLoginLinkForm(LoginLinkForm):
    link_expires_in = 60 * 15  # 15 minutes


class CustomLoginView(LoginLinkFormView):
    form_class = CustomLoginLinkForm
```

A link works for this entire window, not just once (see [Are login links single-use?](#are-login-links-single-use)), so choose a duration you're comfortable handing out for that long. Very short windows fail in practice — corporate mail can take minutes to deliver, and users get distracted mid-signup.

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

#### Are login links single-use?

No. A link works every time it is clicked until it expires. The security boundary is the expiration window, not consuming the link.

This is a deliberate choice. Anyone who can read the inbox can request a fresh link, so a compromised inbox is equally exposed either way — single-use only covers a link that escaped the inbox, was already used, and is still unexpired. Against that narrow gain, marking a link spent on the first request breaks with corporate mail security (Safe Links, Mimecast, Barracuda), which fetches URLs in incoming email and would spend the link before the recipient ever clicks. Avoiding that means landing on a confirmation page and asking every user to click a button to finish signing in.

Set an expiration you are comfortable handing out for that whole window. See [Customizing link expiration](#customizing-link-expiration).

If you need single-use links, build the flow you want on top of [`plain.signing`](/plain/plain/signing.py) rather than reaching for a hook here. `TimestampSigner` covers the token half — [plain.passwords](/plain-passwords/plain/passwords/README.md) signs its reset tokens that way. The other half is storage, since marking a link spent means recording the ones you issued, and where that lives depends on what else you want from it — revocation, an audit trail, per-device rules.

Note that the session created by a login link long outlives the link. Session lifetime and revocation belong to [plain.sessions](/plain-sessions/plain/sessions/README.md).

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
    urls = (
        path("login/", LoginLinkFormView, name="login"),
        include("loginlink/", LoginlinkRouter),
    )
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
