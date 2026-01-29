# Plain Framework

Plain is a Python web framework. Use `uv run plain ...` for all framework commands.

Use the `/plain-install` skill to add new Plain packages.
Use the `/plain-upgrade` skill to upgrade Plain packages.

## Documentation

Run `uv run plain docs --list` to see available packages.
Run `uv run plain docs <package> --source` for detailed API documentation.

Examples:

- `uv run plain docs models --source` - Models and database
- `uv run plain docs templates --source` - Jinja2 templates
- `uv run plain docs assets --source` - Static assets

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
