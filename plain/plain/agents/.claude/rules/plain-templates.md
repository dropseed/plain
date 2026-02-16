---
paths:
  - "**/*.html"
---

# Templates

- Plain uses Jinja2 — run `uv run plain docs templates` for full documentation
- Break HTML tags with many attributes onto multiple lines, closing `>` on its own line
- Render form fields via `form.field.html_name`, `html_id`, `value`, `errors`
- Never call `.query` in templates — all data should come from the view context
