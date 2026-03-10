---
paths:
  - "**/*.html"
---

# Templates

- Plain uses Jinja2 — run `uv run plain docs templates` for full documentation
- Break HTML tags with many attributes onto multiple lines, closing `>` on its own line
- Render form fields manually via `form.field.html_name`, `html_id`, `value`, `errors`
- Never call `.query` in templates — all data should come from the view context

## Differences from Django

- Plain uses Jinja2, not Django's template engine. Most syntax is similar but custom filters differ.
- CSRF is automatic (header-based via Sec-Fetch-Site) — no `{{ csrf_input }}` or `{% csrf_token %}`
- Forms are headless — no `as_p()`, `as_table()`, or `as_elements()`. Validate at form/model level, not just in views.
