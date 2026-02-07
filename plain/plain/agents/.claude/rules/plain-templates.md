---
paths:
  - "**/*.html"
---

# Templates

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
