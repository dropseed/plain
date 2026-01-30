# Plain Framework

Plain is a Python web framework.

- Always use `uv run` to execute commands — never use bare `python` or `plain` directly.
- Plain is a Django fork but has different APIs — never assume Django patterns will work.
- When unsure about an API or something doesn't work, run `uv run plain docs <package>` first. Add `--symbols` if you need the full API surface.
- Use the `/plain-install` skill to add new Plain packages.
- Use the `/plain-upgrade` skill to upgrade Plain packages.

## Documentation

Run `uv run plain docs --list` to see all official packages (installed and uninstalled) with descriptions.
Run `uv run plain docs <package>` for markdown documentation (installed packages only).
Run `uv run plain docs <package> --symbols` for the symbolicated API surface.
For uninstalled packages, the CLI shows the install command and an online docs URL.

Online docs URL pattern: `https://plainframework.com/docs/<pip-name>/<module/path>/README.md`
Example: `https://plainframework.com/docs/plain-models/plain/models/README.md`

Examples:

- `uv run plain docs models` - Models and database docs
- `uv run plain docs models --symbols` - Models API surface
- `uv run plain docs templates` - Jinja2 templates
- `uv run plain docs assets` - Static assets

### All official packages

- **plain** — Web framework core
- **plain-admin** — Backend admin interface
- **plain-api** — Class-based API views
- **plain-auth** — User authentication and authorization
- **plain-cache** — Database-backed cache with optional expiration
- **plain-code** — Preconfigured code formatting and linting
- **plain-dev** — Local development server with auto-reload
- **plain-elements** — HTML template components
- **plain-email** — Send email
- **plain-esbuild** — Build JavaScript with esbuild
- **plain-flags** — Feature flags via database models
- **plain-htmx** — HTMX integration for templates and views
- **plain-jobs** — Background jobs with a database-driven queue
- **plain-loginlink** — Link-based authentication
- **plain-models** — Model data and store it in a database
- **plain-oauth** — OAuth provider login
- **plain-observer** — On-page telemetry and observability
- **plain-pages** — Serve static pages, markdown, and assets
- **plain-pageviews** — Client-side pageview tracking
- **plain-passwords** — Password authentication
- **plain-pytest** — Test with pytest
- **plain-redirection** — URL redirection with admin and logging
- **plain-scan** — Test for production best practices
- **plain-sessions** — Database-backed sessions
- **plain-start** — Bootstrap a new project from templates
- **plain-support** — Support forms for your application
- **plain-tailwind** — Tailwind CSS without JavaScript or npm
- **plain-toolbar** — Debug toolbar
- **plain-tunnel** — Remote access to local dev server
- **plain-vendor** — Vendor CDN scripts and styles

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
