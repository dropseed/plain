# plain.elements

**Build reusable HTML components using a tag-based syntax.**

- [Overview](#overview)
- [Passing attributes](#passing-attributes)
- [Nested content with `children`](#nested-content-with-children)
- [Namespaced elements](#namespaced-elements)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Elements give you a component-like syntax for HTML templates. Instead of using Jinja `{% include %}` or macros, you write components as `.html` files and use them with capitalized HTML tags like `<Button>` or `<Card>`.

To create an element, add a template in `templates/elements/`. The filename becomes the tag name.

```html
<!-- templates/elements/Button.html -->
<button type="button" class="btn btn-primary">
    {{ children }}
</button>
```

To use elements in a template, add `{% use_elements %}` at the top. Then use your element with its capitalized tag name.

```html
{% use_elements %}

<div class="actions">
    <Button>Click me</Button>
</div>
```

The output will be:

```html
<div class="actions">
    <button type="button" class="btn btn-primary">
        Click me
    </button>
</div>
```

## Passing attributes

You can pass attributes to elements in two ways: as strings or as Python expressions.

String attributes use standard HTML syntax:

```html
{% use_elements %}

<Button type="submit">Save</Button>
```

Python expressions use single braces `{}`:

```html
{% use_elements %}

<FormInput field={form.email} label="Email address" />
```

Inside the element template, attributes become template variables:

```html
<!-- templates/elements/FormInput.html -->
<label for="{{ field.html_id }}">{{ label }}</label>
<input
    id="{{ field.html_id }}"
    type="{{ type|default('text') }}"
    name="{{ field.html_name }}"
    value="{{ field.value() or '' }}"
    {% if field.field.required %}required{% endif %}
/>
```

By default, Plain raises an error for undefined variables. Use the `|default` filter or `is defined` test for optional attributes.

## Nested content with `children`

Content between opening and closing tags is available as the `children` variable.

```html
<!-- templates/elements/Card.html -->
<div class="card">
    <div class="card-body">
        {{ children }}
    </div>
</div>
```

```html
{% use_elements %}

<Card>
    <h2>Welcome</h2>
    <p>This content appears inside the card body.</p>
</Card>
```

Self-closing elements don't have children:

```html
{% use_elements %}

<Divider />
```

## Namespaced elements

You can organize elements into subdirectories. This is particularly useful for reusable packages or grouping related components.

Put the element template in a subdirectory of `templates/elements/`:

```html
<!-- templates/elements/forms/Input.html -->
<input type="text" class="form-input" />
```

Use the dot-separated path as the tag name:

```html
{% use_elements %}

<forms.Input />
```

## FAQs

#### Can I nest the same element inside itself?

No. Elements cannot be nested inside themselves to prevent infinite recursion. If you need recursive structures, split them into separate element types.

#### Why use capitalized tag names?

Capitalized names like `<Button>` distinguish your elements from built-in HTML tags like `<button>`. This prevents conflicts and makes it clear which tags are custom components.

#### How does this compare to Jinja macros?

Elements are simpler for component-style usage. Macros require import statements and use function-call syntax. Elements look like HTML and feel more natural when building UIs. Use macros when you need complex logic or multiple return values.

#### Can I use elements without `{% use_elements %}`?

No. The `{% use_elements %}` tag enables element processing for that template. Without it, capitalized tags will be treated as literal text.

## Installation

Install the `plain.elements` package:

```bash
uv add plain.elements
```

Add it to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.elements",
]
```

Create your first element template:

```html
<!-- templates/elements/Alert.html -->
<div class="alert alert-{{ type|default('info') }}">
    {{ children }}
</div>
```

Use it in any template:

```html
{% use_elements %}

<Alert type="success">
    Your changes have been saved.
</Alert>
```
