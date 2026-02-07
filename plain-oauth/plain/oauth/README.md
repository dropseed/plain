# plain.oauth

**Let users log in with OAuth providers like GitHub, Google, and more.**

- [Overview](#overview)
- [Creating a provider](#creating-a-provider)
- [Connecting and disconnecting accounts](#connecting-and-disconnecting-accounts)
- [Using saved access tokens](#using-saved-access-tokens)
- [Customizing the provider](#customizing-the-provider)
- [Settings](#settings)
- [FAQs](#faqs)
    - [How is this different from other OAuth libraries?](#how-is-this-different-from-other-oauth-libraries)
    - [Why are providers not included in the library?](#why-are-providers-not-included-in-the-library)
    - [What if there is a redirect URL mismatch in local development?](#what-if-there-is-a-redirect-url-mismatch-in-local-development)
    - [What does the preflight check do?](#what-does-the-preflight-check-do)
- [Installation](#installation)

## Overview

This package provides a minimal OAuth integration with no dependencies and a single database model. You can let users sign up and log in with GitHub, Google, Twitter, or any other OAuth provider.

Three OAuth flows are supported:

1. **Signup** - new user, new OAuth connection
2. **Login** - existing user, existing OAuth connection
3. **Connect/disconnect** - existing user linking or unlinking an OAuth account

Here is a complete example showing GitHub OAuth login.

```python
# app/oauth.py
import requests

from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser


class GitHubOAuthProvider(OAuthProvider):
    authorization_url = "https://github.com/login/oauth/authorize"

    def get_oauth_token(self, *, code, request):
        response = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": self.get_client_id(),
                "client_secret": self.get_client_secret(),
                "code": code,
            },
        )
        response.raise_for_status()
        data = response.json()
        return OAuthToken(access_token=data["access_token"])

    def get_oauth_user(self, *, oauth_token):
        response = requests.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/json",
                "Authorization": f"token {oauth_token.access_token}",
            },
        )
        response.raise_for_status()
        data = response.json()
        return OAuthUser(
            provider_id=data["id"],
            user_model_fields={
                "email": data["email"],
                "username": data["login"],
            },
        )

    def refresh_oauth_token(self, *, oauth_token):
        # GitHub tokens don't expire by default
        return oauth_token
```

Configure the provider in your settings:

```python
# app/settings.py
OAUTH_LOGIN_PROVIDERS = {
    "github": {
        "class": "app.oauth.GitHubOAuthProvider",
        "kwargs": {
            "client_id": environ["GITHUB_CLIENT_ID"],
            "client_secret": environ["GITHUB_CLIENT_SECRET"],
            # "scope" is optional, defaults to ""
        },
    },
}
```

Add a login button in your template:

```html
<form action="{% url 'oauth:login' 'github' %}" method="post">
    <button type="submit">Login with GitHub</button>
</form>
```

The provider name in the URL (`'github'`) must match the key in `OAUTH_LOGIN_PROVIDERS`. Your callback URL will be `https://yoursite.com/oauth/github/callback/`.

## Creating a provider

You need to subclass [`OAuthProvider`](./providers.py#OAuthProvider) and implement three methods:

- `get_oauth_token` - exchanges an authorization code for an access token
- `get_oauth_user` - fetches user information using the access token
- `refresh_oauth_token` - refreshes an expired access token (return the same token if the provider does not support refresh)

Set the `authorization_url` class attribute to the provider's OAuth authorization endpoint.

The [`OAuthToken`](./providers.py#OAuthToken) class accepts these fields:

```python
OAuthToken(
    access_token="...",
    refresh_token="",  # optional
    access_token_expires_at=None,  # optional datetime
    refresh_token_expires_at=None,  # optional datetime
)
```

The [`OAuthUser`](./providers.py#OAuthUser) class requires a `provider_id` and an optional dict of fields to set on your User model:

```python
OAuthUser(
    provider_id="12345",  # unique ID on the provider's system
    user_model_fields={
        "email": "user@example.com",
        "username": "example_user",
    },
)
```

## Connecting and disconnecting accounts

Authenticated users can connect additional OAuth providers or disconnect existing ones. Add forms to a settings page:

```html
<h2>Connected accounts</h2>
<ul>
    {% for connection in get_current_user().oauth_connections.all %}
    <li>
        {{ connection.provider_key }}
        <form action="{% url 'oauth:disconnect' connection.provider_key %}" method="post">
            <input type="hidden" name="provider_user_id" value="{{ connection.provider_user_id }}">
            <button type="submit">Disconnect</button>
        </form>
    </li>
    {% endfor %}
</ul>

<h2>Add a connection</h2>
<ul>
    {% for provider_key in oauth_provider_keys %}
    <li>
        <form action="{% url 'oauth:connect' provider_key %}" method="post">
            <button type="submit">Connect {{ provider_key }}</button>
        </form>
    </li>
    {% endfor %}
</ul>
```

Use [`get_provider_keys`](./providers.py#get_provider_keys) to populate the list of available providers:

```python
from plain.oauth.providers import get_provider_keys
from plain.views import TemplateView


class SettingsView(TemplateView):
    template_name = "settings.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["oauth_provider_keys"] = get_provider_keys()
        return context
```

## Using saved access tokens

The [`OAuthConnection`](./models.py#OAuthConnection) model stores token data for each connected provider. You can use stored tokens to make API calls on behalf of users.

```python
# Get the connection for a user
connection = user.oauth_connections.get(provider_key="github")

# Check if the token has expired and refresh it
if connection.access_token_expired():
    connection.refresh_access_token()

# Use the token
response = requests.get(
    "https://api.github.com/user/repos",
    headers={"Authorization": f"token {connection.access_token}"},
)
```

## Customizing the provider

The [`OAuthProvider`](./providers.py#OAuthProvider) class has several methods you can override:

- `get_authorization_url_params` - customize the OAuth authorization URL parameters
- `get_login_redirect_url` - change where users are redirected after login
- `get_disconnect_redirect_url` - change where users are redirected after disconnecting
- `login` - customize the login process (uses [plain.auth](/plain-auth/plain/auth/README.md) by default)

## Settings

| Setting                 | Default  | Env var                              |
| ----------------------- | -------- | ------------------------------------ |
| `OAUTH_LOGIN_PROVIDERS` | Required | `PLAIN_OAUTH_LOGIN_PROVIDERS` (JSON) |

This setting is marked as `Secret`, so its values are masked in logs. See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How is this different from other OAuth libraries?

This library does less. Popular alternatives like django-allauth provide features like email verification, multiple email addresses, and dozens of pre-configured providers. That adds complexity you may not need. This library focuses on the core OAuth flow with a single database model and no extra dependencies.

#### Why are providers not included in the library?

Providers are straightforward to implement. You find two OAuth URLs in the provider's docs and write two methods to fetch tokens and user data. This approach means you can fix issues immediately without waiting for upstream updates, and you can customize the implementation for your specific needs.

#### What if there is a redirect URL mismatch in local development?

If you are using a proxy like ngrok, the callback URL might be built as `http` instead of `https`. Add this to your settings:

```python
HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"
```

#### What does the preflight check do?

A preflight check warns you if a provider key exists in your database but is missing from your `OAUTH_LOGIN_PROVIDERS` setting. This prevents errors when users try to use a provider that has been removed from your configuration.

## Installation

Install the package from PyPI:

```bash
uv add plain.oauth
```

Add `plain.oauth` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.oauth",
]
```

Include the [`OAuthRouter`](./urls.py#OAuthRouter) in your URLs:

```python
# app/urls.py
from plain.oauth.urls import OAuthRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthRouter),
        # ...
    ]
```

Run migrations:

```bash
plain migrate
```

Create an OAuth app on your provider's site (GitHub, Google, etc.) and note the client ID and client secret. Set the callback URL to match your configuration, for example `http://localhost:8000/oauth/github/callback/` for local development.

Create a provider class following the [Overview](#overview) example and configure `OAUTH_LOGIN_PROVIDERS` in your settings. Add login buttons to your templates and you are ready to go.
