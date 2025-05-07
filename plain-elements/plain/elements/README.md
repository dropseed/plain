# plain.elements

**Use HTML tags to include HTML template components.**

Elements are an alternative to Jinja [`{% include %}`](https://jinja.palletsprojects.com/en/stable/templates/#include) or [macros](https://jinja.palletsprojects.com/en/stable/templates/#macros) and flow better with existing HTML by using a compatible syntax. They are distinguished from built-in HTML tags by using a capitalized tag name (so `<Button>` doesn't clash with `<button>`).

To make a `<Submit>` element, for example, you would create a template named `templates/elements/Submit.html`.

```html
<!-- templates/elements/Submit.html -->
<button type="submit" class="btn">
    {{ children }}
</button>
```

An element can be used in any other template by enabling them with `{% use_elements %}` and then using the caplitalized tag name.

```html
{% extends "admin/base.html" %}

{% use_elements %}

{% block content %}
<form method="post">
    {{ csrf_input }}
    <!-- Form fields here -->
    <Submit>Save</Submit>
</form>
{% endblock %}
```


## Installation

Install [`plain.elements` from PyPI](https://pypi.org/project/plain.elements/) and add it to your `INSTALLED_PACKAGES` setting. That's it! The Jinja extension will be enabled automatically.

```python
# settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.elements",
]
```

## Element attributes

Attributes will be passed through using regular strings or single braces `{}` for Python variables.

```html
{% extends "admin/base.html" %}

{% use_elements %}

{% block content %}
<form method="post">
    {{ csrf_input }}
    <FormInput field={form.username} placeholder="Username" label="Username" />
    <Submit>Save</Submit>
</form>
{% endblock %}
```

The attributes are passed to the element as named variables. By default in Plain, you will get an error if you try to use an undefined variable, so Jinja features like [`|default`](https://jinja.palletsprojects.com/en/stable/templates/#jinja-filters.default) and [`is defined`](https://jinja.palletsprojects.com/en/stable/templates/#jinja-tests.defined) are useful for optional attributes.

```html
<!-- templates/elements/FormInput.html -->
<label for="{{ field.html_id }}">
    {{ label }}
</label>
<input
    id="{{ field.html_id }}"
    type="{{ type|default('text') }}"
    name="{{ field.html_name }}"
    value="{{ field.value() or '' }}"
    placeholder="{{ placeholder }}"
    {% if field.field.required %}required{% endif %}
    />
```

## Namespaced elements

Especially for reusable packages, it can be useful to namespace your elements by putting them in a subdirectory of `templates/elements/`. To use namespaced elements, you need to include the full dot-separated path in your HTML tag.

For example, an element in `templates/elements/admin/Submit.html` would be used like this:

```html
{% use_elements %}

{% block content %}
<form method="post">
    {{ csrf_input }}
    <admin.Submit>Save</admin.Submit>
</form>
{% endblock %}
```
