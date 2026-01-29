---
paths:
  - "**/*.html"
---

# Tailwind CSS

## Conditional Styling

Use `data-` attributes with Tailwind's `data-` selectors instead of `{% if %}` inside `class` attributes.

**Good:**

```html
<div data-active="{{ is_active }}" class="data-[active=True]:bg-blue-500">
```

**Avoid:**

```html
<div class="{% if is_active %}bg-blue-500{% endif %}">
```

Run `uv run plain docs tailwind --source` for detailed Tailwind integration documentation.
