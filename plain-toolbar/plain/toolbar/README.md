# plain.toolbar

**A developer toolbar that displays debugging information in your browser.**

- [Overview](#overview)
- [Built-in panels](#built-in-panels)
    - [Request panel](#request-panel)
    - [Exception panel](#exception-panel)
- [Creating custom toolbar items](#creating-custom-toolbar-items)
    - [Button-only items](#button-only-items)
- [Visibility](#visibility)
- [JavaScript API](#javascript-api)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The toolbar appears at the bottom of your browser window and shows useful debugging information about the current request. You can expand it to see detailed panels, switch between tabs, and resize it by dragging the top edge.

To render the toolbar, add the `{% toolbar %}` tag to your base template (typically just before the closing `</body>` tag):

```html
<!DOCTYPE html>
<html>
<head>
    <title>My App</title>
</head>
<body>
    {% block content %}{% endblock %}

    {% toolbar %}
</body>
</html>
```

The toolbar automatically hides itself in production unless the user is an admin. In debug mode, it always appears.

## Built-in panels

### Request panel

The Request panel shows information about the current HTTP request:

- Request ID
- Query parameters
- HTTP method
- View class
- URL pattern, name, args, and kwargs
- Template names (if available)
- Primary object (if the view has an `object` attribute)

### Exception panel

When an exception occurs during request handling, the Exception panel automatically appears with:

- The exception type and message
- A color-coded traceback showing frames from your app, Plain, third-party packages, and Python stdlib
- Source code context around each frame (expandable/collapsible)
- Local variables for each frame (in debug mode)
- A "Copy" button to copy the full exception for sharing
- A "View raw" button to see the standard Python traceback format
- Clickable file paths that open in VS Code

App frames are highlighted in amber and expanded by default, making it easy to spot where the error occurred in your code.

## Creating custom toolbar items

You can add your own panels to the toolbar by creating a `ToolbarItem` subclass and registering it with the `@register_toolbar_item` decorator.

Create a `toolbar.py` file in any installed app:

```python
# app/users/toolbar.py
from plain.toolbar import ToolbarItem, register_toolbar_item


@register_toolbar_item
class UserToolbarItem(ToolbarItem):
    name = "User"
    panel_template_name = "toolbar/user.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["current_user"] = getattr(self.request, "user", None)
        return context
```

Then create the panel template:

```html
<!-- app/users/templates/toolbar/user.html -->
<div class="px-6 py-4 text-sm">
    {% if current_user %}
    <dl class="grid grid-cols-[max-content_1fr] gap-x-8 gap-y-2">
        <dt>Email</dt>
        <dd class="text-white/50">{{ current_user.email }}</dd>
        <dt>ID</dt>
        <dd class="text-white/50">{{ current_user.id }}</dd>
    </dl>
    {% else %}
    <p class="text-white/50">No user logged in</p>
    {% endif %}
</div>
```

The toolbar uses autodiscovery to find `toolbar.py` files in all installed apps.

### Button-only items

You can also create toolbar items that only show a button in the minimized toolbar bar (no expandable panel). Set `button_template_name` instead of `panel_template_name`:

```python
@register_toolbar_item
class QuickActionToolbarItem(ToolbarItem):
    name = "QuickAction"
    button_template_name = "toolbar/quick_action_button.html"

    def is_enabled(self):
        # Only show when a certain condition is met
        return some_condition
```

Override `is_enabled()` to control when your toolbar item appears.

## Visibility

The toolbar only renders when `Toolbar.should_render()` returns `True`. This happens when:

1. `DEBUG` is `True`, or
2. The user has `is_admin = True`, or
3. An admin is impersonating another user (requires `plain.admin`)

You can also temporarily hide the toolbar:

- Click the X button to hide it for the current session
- Click the clock icon to hide it for 1 hour (stored in localStorage)
- Call `plainToolbar.show()` in the browser console to bring it back

## JavaScript API

The toolbar exposes a `window.plainToolbar` object for programmatic control:

```javascript
// Show/hide the toolbar
plainToolbar.show();
plainToolbar.hide();

// Expand/collapse the details panel
plainToolbar.expand();
plainToolbar.collapse();
plainToolbar.toggleExpand();

// Show a specific tab
plainToolbar.showTab("Request");
plainToolbar.showTab("Exception");

// Hide for a duration (milliseconds from now)
plainToolbar.hideUntil(Date.now() + 3600000);  // Hide for 1 hour

// Reset custom height
plainToolbar.resetHeight();
```

## FAQs

#### How do I style my custom panel?

The toolbar uses Tailwind CSS classes. Your panel template has access to all Tailwind utilities. The toolbar has a dark theme, so use light text colors like `text-white`, `text-stone-300`, or `text-white/50` for muted text.

#### Can I add multiple custom panels?

Yes. Create multiple `ToolbarItem` subclasses, each with its own `name` and templates. They will appear as separate tabs in the toolbar.

#### Why does the Exception panel open automatically?

When an exception occurs, the toolbar automatically expands and shows the Exception panel so you can immediately see what went wrong. This behavior is intentional to surface errors quickly during development.

#### How do I disable the toolbar completely?

Remove `plain.toolbar` from your `INSTALLED_PACKAGES` setting. Alternatively, remove the `{% toolbar %}` tag from your templates.

## Installation

Install the `plain.toolbar` package from PyPI:

```console
uv add plain.toolbar
```

Add `plain.toolbar` to your `INSTALLED_PACKAGES` in `app/settings.py`:

```python
INSTALLED_PACKAGES = [
    # ... other packages
    "plain.toolbar",
]
```

Add the `{% toolbar %}` template tag to your base template, just before the closing `</body>` tag:

```html
<!DOCTYPE html>
<html>
<head>
    <title>My App</title>
</head>
<body>
    {% block content %}{% endblock %}

    {% toolbar %}
</body>
</html>
```

A `VERSION` setting is required in your `app/settings.py` to display in the toolbar:

```python
VERSION = "1.0.0"
```

The toolbar should now appear at the bottom of your browser window in debug mode.
