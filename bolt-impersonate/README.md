# forge-impersonate

A key feature for providing customer support is to be able to view the site through their account.
With `impersonate` installed, you can impersonate a user by finding them in the Django admin and clicking the "Impersonate" button.

![](/docs/img/impersonate-admin.png)

Then with the [staff toolbar](/docs/forge-stafftoolbar/) enabled, you'll get a notice of the impersonation and a button to exit:

![](/docs/img/impersonate-bar.png)

## Installation

To impersonate users, you need the app, middleware, and URLs:

```python
# settings.py
INSTALLED_APPS = INSTALLED_APPS + [
  "forgeimpersonate",
]

MIDDLEWARE = MIDDLEWARE + [
  "forgeimpersonate.ImpersonateMiddleware",
]
```

```python
# urls.py
urlpatterns = [
    # ...
    path("impersonate/", include("forgeimpersonate.urls")),
]
```

## Settings

By default, all staff users can impersonate other users.

```python
# settings.py
IMPERSONATE_ALLOWED = lambda user: user.is_superuser or user.is_staff
```

> Note: Regardless of who is allowed to be an impersonator, nobody can impersonate a superuser!
