# plain.impersonate

See what your users see.

A key feature for providing customer support is to be able to view the site through their account.
With `impersonate` installed, you can impersonate a user by finding them in the Django admin and clicking the "Impersonate" button.

![](/docs/img/impersonate-admin.png)

Then with the [admin toolbar](/docs/plain-toolbar/) enabled, you'll get a notice of the impersonation and a button to exit:

![](/docs/img/impersonate-bar.png)

## Installation

To impersonate users, you need the app, middleware, and URLs:

```python
# settings.py
INSTALLED_PACKAGES = INSTALLED_PACKAGES + [
  "plain.admin.impersonate",
]

MIDDLEWARE = MIDDLEWARE + [
  "plain.admin.impersonate.ImpersonateMiddleware",
]
```

```python
# urls.py
urlpatterns = [
    # ...
    path("impersonate/", include("plain.admin.impersonate.urls")),
]
```

## Settings

By default, all admin users can impersonate other users.

```python
# settings.py
IMPERSONATE_ALLOWED = lambda user: user.is_admin
```
