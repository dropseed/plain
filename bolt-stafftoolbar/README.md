# forge-stafftoolbar

The staff toolbar is enabled for every user who `is_staff`.

![Forge staff toolbar](https://user-images.githubusercontent.com/649496/213781915-a2094f54-99b8-4a05-a36e-dee107405229.png)

## Installation

Add `forgestafftoolbar` to your `INSTALLED_APPS`,
and the `{% stafftoolbar %}` to your base template:

```python
# settings.py
INSTALLED_APPS += [
    "forgestafftoolbar",
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
from forgestafftoolbar import StaffToolbarLink


STAFFTOOLBAR_LINKS = [
    StaffToolbarLink(text="Admin", url="admin:index"),
]
```

## Container class

To make the toolbar better match your layout,
you can change the classes via the template tag:

```html
<!-- base.html -->
{% stafftoolbar outer_class="fixed bottom-0 w-full" inner_class="max-w-4xl mx-auto" %}
```
