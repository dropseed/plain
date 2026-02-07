# Plain Framework

Plain is a Python web framework.

- Always use `uv run` to execute commands — never use bare `python` or `plain` directly.
- Plain is a Django fork but has different APIs — never assume Django patterns will work.
- When unsure about an API or something doesn't work, run `uv run plain docs <package>` first. Add `--api` if you need the full API surface.
- Use the `/plain-install` skill to add new Plain packages.
- Use the `/plain-upgrade` skill to upgrade Plain packages.

## Key Differences from Django

Claude's training data contains a lot of Django code. These are the most common patterns that differ in Plain:

- **Querysets**: Use `Model.query` not `Model.objects` (e.g., `User.query.filter(is_active=True)`)
- **Field types**: Import from `plain.models.types` not `plain.models.fields`
- **Templates**: Plain uses Jinja2, not Django's template engine. Most syntax is similar but filters use `|` with function call syntax (e.g., `{{ name|title }}` works, but custom filters differ)
- **URLs**: Use `Router` with `urls` list, not Django's `urlpatterns`
- **Tests**: Use `plain.test.Client`, not `django.test.Client`
- **Settings**: Use `plain.runtime.settings`, not `django.conf.settings`

When in doubt, run `uv run plain docs <package> --api` to check the actual API.

## Documentation

Run `uv run plain docs --list` to see available packages.
Run `uv run plain docs <package>` for markdown documentation.
Run `uv run plain docs <package> --api` for the symbolicated API surface.

Examples:

- `uv run plain docs models` - Models and database docs
- `uv run plain docs models --api` - Models API surface
- `uv run plain docs templates` - Jinja2 templates
- `uv run plain docs assets` - Static assets

## Shell

`uv run plain shell` opens an interactive Python shell with Plain configured and database access.

Run a one-off command:

```
uv run plain shell -c "from app.users.models import User; print(User.query.count())"
```

Run a script:

```
uv run plain run script.py
```

## HTTP Requests

Use `uv run plain request` to make test HTTP requests against the dev database.

```
uv run plain request /path
uv run plain request /path --user 1
uv run plain request /path --header "Accept: application/json"
uv run plain request /path --method POST --data '{"key": "value"}'
uv run plain request /path --no-body    # Headers only
uv run plain request /path --no-headers # Body only
```
