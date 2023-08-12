# bolt-querystats

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
INSTALLED_APPS = [
    # ...
    "boltquerystats",
]

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",
    "bolt.middleware.common.CommonMiddleware",
    "bolt.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",

    "boltquerystats.QueryStatsMiddleware",
    # Put additional middleware below querystats
    # ...
]
```

We strongly recommend using the bolt-stafftoolbar along with this,
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


# bolt-stafftoolbar

The staff toolbar is enabled for every user who `is_staff`.

![Bolt staff toolbar](https://user-images.githubusercontent.com/649496/213781915-a2094f54-99b8-4a05-a36e-dee107405229.png)

## Installation

Add `boltstafftoolbar` to your `INSTALLED_APPS`,
and the `{% stafftoolbar %}` to your base template:

```python
# settings.py
INSTALLED_APPS += [
    "boltstafftoolbar",
]
```

```html
<!-- base.template.html -->
{% load stafftoolbar %}
<!doctype html>
<html lang="en">
  <head>
    ...
  </head>
  <body>
    {% stafftoolbar %}
    ...
  </body>
```

More specific settings can be found below.


## Custom links

Staff links are shown on the right-hand side of the toolbar and can be customzed.
By default, it shows a link back to the Django admin:

```python
# settings.py
from django.urls import reverse_lazy


STAFFTOOLBAR_LINKS = [
    ("Admin", reverse_lazy("admin:index")),
]
```

## Container class

To make the toolbar better match your layout,
you can change the classes via the template tag:

```html
<!-- base.html -->
{% stafftoolbar outer_class="fixed bottom-0 w-full" inner_class="max-w-4xl mx-auto" %}
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
INSTALLED_APPS += [
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
REQUESTLOG_IGNORE_URL_PATHS = [
    "/sw.js",
    "/favicon.ico",
    "/admin/jsi18n/",
]
REQUESTLOG_KEEP_LATEST = 50
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
