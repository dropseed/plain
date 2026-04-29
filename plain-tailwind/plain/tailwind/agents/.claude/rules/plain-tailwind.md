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

## Package CSS contributions

A package can contribute CSS to the user's Tailwind build by shipping a
`tailwind.css` next to its `__init__.py`. `plain-tailwind` auto-discovers it
and adds an `@import` line to `.plain/tailwind.css` — no user setup needed.

Use this for design tokens (`@theme`), component layers (`@apply`-based rules
inside `@layer components`), or `@custom-variant`s that need to be part of
the Tailwind compilation. Keep raw Tailwind utility classes out of this file
— those belong in templates, where they're picked up by the `@source` scan.
