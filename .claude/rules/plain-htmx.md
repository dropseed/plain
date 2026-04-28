# HTMX

## View dispatching

`HTMXView` routes HTMX requests to handler methods based on HTTP method and action:

- `htmx_{method}` — e.g., `htmx_post` handles any HTMX POST
- `htmx_{method}_{action}` — e.g., `htmx_post_toggle_pin` handles `plain-hx-action="toggle_pin"`

Detection: checks `HX-Request: true` header. Action comes from `Plain-HX-Action` header.

## Handler return values

Action handlers return `Response | None`:

- `return None` (or fall off the end) — re-render the current template/fragment. This is the default for "mutate state, send back the new fragment".
- `return Response(...)` — only when diverging from a re-render: `RedirectResponse`, a 204 with `HX-Redirect`, JSON, etc.

Never wrap `self.render_template()` in `Response(...)` yourself — just return `None`.

## Testing HTMX endpoints with `plain request`

HTMX sends form-encoded POST requests with specific headers. Simulate with:

```
uv run plain request /path --user 1 --method POST \
  --header "HX-Request: true" \
  --header "Plain-HX-Action: action_name" \
  --data "key=val&key2=val2"
```

Omit `--data` for actions that don't send data. `--data "key=val"` auto-detects as form-encoded.

Run `uv run plain docs htmx` for full documentation.
