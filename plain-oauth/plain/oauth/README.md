# plain.oauth

**Let users log in with OAuth providers.**

- [Overview](#overview)
- [Usage](#usage)
    - [Basic setup example](#basic-setup-example)
    - [Handling OAuth errors](#handling-oauth-errors)
    - [Connecting and disconnecting OAuth accounts](#connecting-and-disconnecting-oauth-accounts)
    - [Using a saved access token](#using-a-saved-access-token)
    - [Using the Django system check](#using-the-django-system-check)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

[Watch on YouTube (3 mins) →](https://www.youtube.com/watch?v=UxbxBa6AFsU)

This library is intentionally minimal.
It has no dependencies and a single database model.
If you simply want users to log in with GitHub, Google, Twitter, etc. (and maybe use that access token for API calls),
then this is the library for you.

There are three OAuth flows that it makes possible:

1. Signup via OAuth (new user, new OAuth connection)
2. Login via OAuth (existing user, existing OAuth connection)
3. Connect/disconnect OAuth accounts to a user (existing user, new OAuth connection)

## Usage

### Basic setup example

Here's a complete example showing how to set up OAuth login with GitHub:

Add `plain.oauth` to your `INSTALLED_PACKAGES` in `settings.py`:

```python
INSTALLED_PACKAGES = [
    ...
    "plain.oauth",
]
```

In your `urls.py`, include the [`OAuthRouter`](./urls.py#OAuthRouter):

```python
from plain.oauth.urls import OAuthRouter
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthRouter),
        # ...
    ]
```

Then run migrations:

```sh
plain migrate plain.oauth
```

Create a new OAuth provider ([or copy one from our examples](https://github.com/forgepackages/plain-oauth/tree/master/provider_examples)):

```python
# yourapp/oauth.py
import requests

from plain.oauth.providers import OAuthProvider, OAuthToken, OAuthUser


class GitHubOAuthProvider(OAuthProvider):
    authorization_url = "https://github.com/login/oauth/authorize"

    def get_oauth_token(self, *, code, request):
        response = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={
                "Accept": "application/json",
            },
            data={
                "client_id": self.get_client_id(),
                "client_secret": self.get_client_secret(),
                "code": code,
            },
        )
        response.raise_for_status()
        data = response.json()
        return OAuthToken(
            access_token=data["access_token"],
        )

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
            # The provider ID is required
            provider_id=data["id"],
            # Populate your User model fields using the user_model_fields dict
            user_model_fields={
                "email": data["email"],
                "username": data["username"],
            },
        )
```

Create your OAuth app/consumer on the provider's site (GitHub, Google, etc.).
When setting it up, you'll likely need to give it a callback URL.
In development this can be `http://localhost:8000/oauth/github/callback/` (if you name it `"github"` like in the example below).
At the end you should get some sort of "client id" and "client secret" which you can then use in your `settings.py`:

```python
OAUTH_LOGIN_PROVIDERS = {
    "github": {
        "class": "yourapp.oauth.GitHubOAuthProvider",
        "kwargs": {
            "client_id": environ["GITHUB_CLIENT_ID"],
            "client_secret": environ["GITHUB_CLIENT_SECRET"],
            # "scope" is optional, defaults to ""

            # You can add other fields if you have additional kwargs in your class __init__
            # def __init__(self, *args, custom_arg="default", **kwargs):
            #     self.custom_arg = custom_arg
            #     super().__init__(*args, **kwargs)
        },
    },
}
```

Then add a login button (which is a form using POST rather than a basic link, for security purposes):

```html
<h1>Login</h1>
<form action="{% url 'oauth:login' 'github' %}" method="post">
    <button type="submit">Login with GitHub</button>
</form>
```

Depending on your URL and provider names,
your OAuth callback will be something like `https://example.com/oauth/{provider}/callback/`.

That's pretty much it!

### Handling OAuth errors

The most common error you'll run into is if an existing user clicks a login button,
but they haven't yet connected that provider to their account.
For security reasons,
the required flow here is that the user actually logs in with another method (however they signed up) and then _connects_ the OAuth provider from a settings page.

For this error (and a couple others),
there is an error template that is rendered.
You can customize this by copying `oauth/error.html` to one of your own template directories:

```html
{% extends "base.html" %}

{% block content %}
<h1>OAuth Error</h1>
<p>{{ oauth_error }}</p>
{% endblock %}
```

![Django OAuth duplicate email address error](https://user-images.githubusercontent.com/649496/159065848-b4ee6e63-9aa0-47b5-94e8-7bee9b509e60.png)

### Connecting and disconnecting OAuth accounts

To connect and disconnect OAuth accounts,
you can add a series of forms to a user/profile settings page.
Here's an very basic example:

```html
{% extends "base.html" %}

{% block content %}
Hello {{ request.user }}!

<h2>Existing connections</h2>
<ul>
    {% for connection in request.user.oauth_connections.all %}
    <li>
        {{ connection.provider_key }} [ID: {{ connection.provider_user_id }}]
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
        {{ provider_key}}
        <form action="{% url 'oauth:connect' provider_key %}" method="post">
            <button type="submit">Connect</button>
        </form>
    </li>
    {% endfor %}
</ul>

{% endblock %}
```

The [`get_provider_keys`](./providers.py#get_provider_keys) function can help populate the list of options:

```python
from plain.oauth.providers import get_provider_keys

class ExampleView(TemplateView):
    template_name = "index.html"

    def get_context(self, **kwargs):
        context = super().get_context(**kwargs)
        context["oauth_provider_keys"] = get_provider_keys()
        return context
```

![Connecting and disconnecting Django OAuth accounts](https://user-images.githubusercontent.com/649496/159065096-30239a1f-62f6-4ee2-a944-45140f45af6f.png)

### Using a saved access token

```python
import requests

# Get the OAuth connection for a user
connection = user.oauth_connections.get(provider_key="github")

# If the token can expire, check and refresh it
if connection.access_token_expired():
    connection.refresh_access_token()

# Use the token in an API call
token = connection.access_token
response = requests.get(...)
```

### Using the Django system check

This library comes with a Django system check to ensure you don't _remove_ a provider from `settings.py` that is still in use in your database.
You do need to specify the `--database` for this to run when using the check command by itself:

```sh
plain check --database default
```

## FAQs

#### How is this different from [Django OAuth libraries](https://djangopackages.org/grids/g/oauth/)?

The short answer is that _it does less_.

In [django-allauth](https://github.com/pennersr/django-allauth)
(maybe the most popular alternative)
you get all kinds of other features like managing multiple email addresses,
email verification,
a long list of supported providers,
and a whole suite of forms/urls/views/templates/signals/tags.
And in my experience,
it's too much.
It often adds more complexity to your app than you actually need (or want) and honestly it can just be a lot to wrap your head around.
Personally, I don't like the way that your OAuth settings are stored in the database vs when you use `settings.py`,
and the implications for doing it one way or another.

The other popular OAuth libraries have similar issues,
and I think their _weight_ outweighs their usefulness for 80% of the use cases.

#### Why aren't providers included in the library itself?

One thing you'll notice is that we don't have a long list of pre-configured providers in this library.
Instead, we have some examples (which you can usually just copy, paste, and use) and otherwise encourage you to wire up the provider yourself.
Often times all this means is finding the two OAuth URLs ("oauth/authorize" and "oauth/token") in their docs,
and writing two class methods that do the actual work of getting the user's data (which is often customized anyway).

We've written examples for the following providers:

- [GitHub](https://github.com/forgepackages/plain-oauth/tree/master/provider_examples/github.py)
- [GitLab](https://github.com/forgepackages/plain-oauth/tree/master/provider_examples/gitlab.py)
- [Bitbucket](https://github.com/forgepackages/plain-oauth/tree/master/provider_examples/bitbucket.py)

Just copy that code and paste it in your project.
Tweak as necessary!

This might sound strange at first.
But in the long run we think it's actually _much_ more maintainable for both us (as library authors) and you (as app author).
If something breaks with a provider, you can fix it immediately!
You don't need to try to run changes through us or wait for an upstream update.
You're welcome to contribute an example to this repo,
and there won't be an expectation that it "works perfectly for every use case until the end of time".

#### Redirect/callback URL mismatch in local development?

If you're doing local development through a proxy/tunnel like [ngrok](https://ngrok.com/),
then the callback URL might be automatically built as `http` instead of `https`.

This is the Django setting you're probably looking for:

```python
HTTPS_PROXY_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

## Installation

Install the `plain.oauth` package from [PyPI](https://pypi.org/project/plain.oauth/):

```bash
uv add plain.oauth
```

After installation, follow the basic setup example in the [Usage](#usage) section above to:

1. Add `plain.oauth` to your `INSTALLED_PACKAGES`
2. Include the OAuth router in your URLs
3. Run migrations
4. Create an OAuth provider class
5. Configure OAuth settings
6. Add login buttons to your templates

For a complete working example, see the [Basic setup example](#basic-setup-example) which shows how to set up GitHub OAuth login.
