---
paths:
  - "**/*.html"
---

# Templates

Plain uses Jinja2 for templates. Run `uv run plain docs templates` for full documentation.

## Formatting

- Break HTML tags with many attributes onto multiple lines, closing `>` on its own line
- Run `uv run plain docs templates --section formatting` for examples

## Forms

- Forms are headless — render fields via `form.field.html_name`, `html_id`, `value`, `errors`
- No `as_p()`, `as_table()`, or `as_elements()` — build your own markup
- Run `uv run plain docs templates --section forms` for a full form example

## CSRF

- CSRF is automatic via the `Sec-Fetch-Site` header — no tokens needed in templates
- Do not add `{{ csrf_input }}` or `{% csrf_token %}`

## Query Safety

- Never call `.query` in templates — all data should come from the view context
- If you see `.query.all()` or `.query.filter()` in a template, move it to the view
