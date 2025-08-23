# plain.toolbar

**Debug toolbar for Plain applications.**

## Installation

```bash
uv add plain.toolbar
```

Add it to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.toolbar",
    # other packages...
]
```

Add the toolbar to your base template:

```html
<!-- app/templates/base.html -->
<!DOCTYPE html>
<html>
<body>
    {% block content required %}{% endblock %}
    {% toolbar %}
</body>
</html>
```

The toolbar will appear when `settings.DEBUG` is True or when `request.user.is_admin` is True.
