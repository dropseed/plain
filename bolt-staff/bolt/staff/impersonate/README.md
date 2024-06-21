# bolt-impersonate

See what your users see.

A key feature for providing customer support is to be able to view the site through their account.
With `impersonate` installed, you can impersonate a user by finding them in the Django admin and clicking the "Impersonate" button.

![](/docs/img/impersonate-admin.png)

Then with the [staff toolbar](/docs/bolt-toolbar/) enabled, you'll get a notice of the impersonation and a button to exit:

![](/docs/img/impersonate-bar.png)

## Installation

To impersonate users, you need the app, middleware, and URLs:

```python
# settings.py
INSTALLED_PACKAGES = INSTALLED_PACKAGES + [
  "bolt.staff.impersonate",
]

MIDDLEWARE = MIDDLEWARE + [
  "bolt.staff.impersonate.ImpersonateMiddleware",
]
```

```python
# urls.py
urlpatterns = [
    # ...
    path("impersonate/", include("bolt.staff.impersonate.urls")),
]
```

## Settings

By default, all staff users can impersonate other users.

```python
# settings.py
IMPERSONATE_ALLOWED = lambda user: user.is_staff
```
