## Admin

An admin interface for staff users.

The Bolt Admin is a new packages built from the ground up.
It leverages class-based views and standard URLs and templates to provide a flexible admin where
you can quickly create your own pages and cards,
in addition to models.

- cards
- dashboards
- diy forms
- detached from login (do your own login (oauth, passkeys, etc))

## Installation

- install bolt.staff and bolt.htmx, add bolt.staff.admin and bolt.htmx to installed packages
- add url

## Models in the admin

## Dashboards

<!-- # bolt-querystats

On-page database query stats in development and production.

On each page, the query stats will display how many database queries were performed and how long they took.

[Watch on YouTube](https://www.youtube.com/watch?v=NX8VXxVJm08)

Clicking the stats in the toolbar will show the full SQL query log with tracebacks and timings.
This is even designed to work in production,
making it much easier to discover and debug performance issues on production data!

![Django query stats](https://user-images.githubusercontent.com/649496/213781593-54197bb6-36a8-4c9d-8294-5b43bd86a4c9.png)

It will also point out duplicate queries,
which can typically be removed by using `select_related`,
`prefetch_related`, or otherwise refactoring your code.

## Installation

```python
# settings.py
INSTALLED_PACKAGES = [
    # ...
    "bolt.staff.querystats",
]

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "bolt.auth.middleware.AuthenticationMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",

    "bolt.staff.querystats.QueryStatsMiddleware",
    # Put additional middleware below querystats
    # ...
]
```

We strongly recommend using the bolt-toolbar along with this,
but if you aren't,
you can add the querystats to your frontend templates with this include:

```html
{% include "querystats/button.html" %}
```

*Note that you will likely want to surround this with an if `DEBUG` or `is_staff` check.*

To view querystats you need to send a POST request to `?querystats=store` (i.e. via a `<form>`),
and the template include is the easiest way to do that.

## Tailwind CSS

This package is styled with [Tailwind CSS](https://tailwindcss.com/),
and pairs well with [`bolt-tailwind`](https://github.com/boltpackages/bolt-tailwind).

If you are using your own Tailwind implementation,
you can modify the "content" in your Tailwind config to include any Bolt packages:

```js
// tailwind.config.js
module.exports = {
  content: [
    // ...
    ".venv/lib/python*/site-packages/bolt*/**/*.{html,js}",
  ],
  // ...
}
```

If you aren't using Tailwind, and don't intend to, open an issue to discuss other options.


# bolt-toolbar

The staff toolbar is enabled for every user who `is_staff`.

![Bolt staff toolbar](https://user-images.githubusercontent.com/649496/213781915-a2094f54-99b8-4a05-a36e-dee107405229.png)

## Installation

Add `bolttoolbar` to your `INSTALLED_PACKAGES`,
and the `{% toolbar %}` to your base template:

```python
# settings.py
INSTALLED_PACKAGES += [
    "bolttoolbar",
]
```

```html
<!-- base.template.html -->
{% load toolbar %}
<!doctype html>
<html lang="en">
  <head>
    ...
  </head>
  <body>
    {% toolbar %}
    ...
  </body>
```

More specific settings can be found below.

## Tailwind CSS

This package is styled with [Tailwind CSS](https://tailwindcss.com/),
and pairs well with [`bolt-tailwind`](https://github.com/boltpackages/bolt-tailwind).

If you are using your own Tailwind implementation,
you can modify the "content" in your Tailwind config to include any Bolt packages:

```js
// tailwind.config.js
module.exports = {
  content: [
    // ...
    ".venv/lib/python*/site-packages/bolt*/**/*.{html,js}",
  ],
  // ...
}
```

If you aren't using Tailwind, and don't intend to, open an issue to discuss other options.


# bolt-requestlog

The request log stores a local history of HTTP requests and responses during `bolt work` (Django runserver).

The request history will make it easy to see redirects,
400 and 500 level errors,
form submissions,
API calls,
webhooks,
and more.

[Watch on YouTube](https://www.youtube.com/watch?v=AwI7Pt5oZnM)

Requests can be re-submitted by clicking the "replay" button.

[![Django request log](https://user-images.githubusercontent.com/649496/213781414-417ad043-de67-4836-9ef1-2b91404336c3.png)](https://user-images.githubusercontent.com/649496/213781414-417ad043-de67-4836-9ef1-2b91404336c3.png)

## Installation

```python
# settings.py
INSTALLED_PACKAGES += [
    "boltrequestlog",
]

MIDDLEWARE = MIDDLEWARE + [
    # ...
    "boltrequestlog.RequestLogMiddleware",
]
```

The default settings can be customized if needed:

```python
# settings.py
DEV_REQUESTS_IGNORE_PATHS = [
    "/sw.js",
    "/favicon.ico",
    "/admin/jsi18n/",
]
DEV_REQUESTS_MAX = 50
```

## Tailwind CSS

This package is styled with [Tailwind CSS](https://tailwindcss.com/),
and pairs well with [`bolt-tailwind`](https://github.com/boltpackages/bolt-tailwind).

If you are using your own Tailwind implementation,
you can modify the "content" in your Tailwind config to include any Bolt packages:

```js
// tailwind.config.js
module.exports = {
  content: [
    // ...
    ".venv/lib/python*/site-packages/bolt*/**/*.{html,js}",
  ],
  // ...
}
```

If you aren't using Tailwind, and don't intend to, open an issue to discuss other options.


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
``` -->
