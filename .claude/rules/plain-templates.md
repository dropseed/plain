---
paths:
  - "**/*.html"
---

# Templates

- Plain uses Jinja2 — run `uv run plain docs templates` for full documentation
- Break HTML tags with many attributes onto multiple lines, closing `>` on its own line
- Render form fields via `form.field.html_name`, `html_id`, `value`, `errors`
- Never call `.query` in templates — all data should come from the view context

## Long Lines

When an HTML tag has many attributes or a long class list, break it into multiple lines with each attribute indented. The closing `>` goes on its own line.

**Good:**

```html
<div
    class="flex items-center justify-between gap-4 rounded-lg border bg-white p-4 shadow-sm"
    data-active="{{ is_active }}"
>
    ...
</div>
```

**Avoid:**

```html
<div class="flex items-center justify-between gap-4 rounded-lg border bg-white p-4 shadow-sm" data-active="{{ is_active }}">...</div>
```
