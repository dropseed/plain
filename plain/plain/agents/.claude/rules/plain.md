# Plain Framework

Plain is a Python web framework.

- Always use `uv run` to execute commands — never use bare `python` or `plain` directly.
- Plain is a Django fork but has different APIs — never assume Django patterns will work.
- When unsure about an API or something doesn't work, run `uv run plain docs <package>` first. Add `--api` if you need the full API surface.
- Use the `/plain-install` skill to add new Plain packages.
- Use the `/plain-upgrade` skill to upgrade Plain packages.

## Coding style

- **Painfully obvious over clever** — blatant clarity, even if it means more code. You should _see_ what is happening, not have to deduce it.
- **Write code meant to be read** — clear names, natural flow, obvious structure. The next person reading it should understand it immediately.
- **Simplify to the present need** — if it feels overcomplicated, it is. Get right to the heart of the issue.

## Settings

Settings live in `app/settings.py` and are accessed via `plain.runtime.settings`.

- Type-annotated settings can be set via `PLAIN_`-prefixed environment variables (e.g., `PLAIN_SECRET_KEY`, `PLAIN_DEBUG=true`). Env vars take highest precedence — they override `settings.py` values. When suggesting how to configure a setting, mention the env var option.
- `uv run plain settings list` — list all settings with current values and sources
- `uv run plain settings get <SETTING_NAME>` — get a specific setting's value

- Never use `getattr(settings, "X", default)` — all known settings have defaults registered by their packages, so `settings.X` always works. Using `getattr` masks typos and missing package installs.

Run `uv run plain docs runtime` for full details on env var syntax, `.env` files, custom prefixes, and package settings.

## Key Differences from Django

Plain is a Django fork but has different APIs. Package-specific differences are in their respective rules (plain-postgres, plain-templates, plain-test). These are the core framework differences:

- **URLs**: Use `Router` with `urls` list, not Django's `urlpatterns`
- **Request data**: Use `request.query_params` not `request.GET`, `request.form_data` not `request.POST`, `request.json_data` not `json.loads(request.body)`, `request.files` not `request.FILES`
- **Middleware**: Middleware uses `before_request(self, request) -> Response | None` and `after_response(self, request, response) -> Response` — not Django's `__init__(self, get_response)` / `__call__` pattern. No `AuthMiddleware` exists — auth works through sessions + view-level checks (`AuthViewMixin`).

When in doubt, run `uv run plain docs <package> --api` to check the actual API.

## Logging

- **Message format**: Capitalized sentence fragments — `"User logged in"`, `"Payment failed"`, not snake_case tokens or inline key=value
- **No f-strings or % formatting** in log messages — pass variable data via `context={}` instead
- Use `context={}` for `app_logger`, `extra={"context": {...}}` for standard loggers (`logging.getLogger("plain.xxx")`)

Run `uv run plain docs logs --section message-format` for full examples and anti-patterns.

## Documentation

**Discovery** — find what's available and where things are:

- `uv run plain docs --list` — all packages and core modules with descriptions
- `uv run plain docs --outline` — section headings for all installed docs
- `uv run plain docs <name> --outline` — section headings (with `###` subsections) for one module
- `uv run plain docs --search <term>` — find which modules/sections mention a term (compact, one line per section)

**Reading** — get full content:

- `uv run plain docs <name>` — full markdown docs
- `uv run plain docs <name> --section <name>` — one specific `##` section
- `uv run plain docs <name> --search <term>` — full content of all matching sections in that module
- `uv run plain docs <name> --api` — public API surface (classes, functions, signatures)

**Workflow**: Use `--search <term>` to find which module has what you need, then `<name> --search <term>` to get the full sections, or `<name> --section <name>` for a specific one.

Packages: plain, plain-admin, plain-api, plain-auth, plain-cache, plain-code, plain-dev, plain-elements, plain-email, plain-esbuild, plain-flags, plain-htmx, plain-jobs, plain-loginlink, plain-portal, plain-postgres, plain-oauth, plain-observer, plain-pages, plain-pageviews, plain-passwords, plain-pytest, plain-redirection, plain-scan, plain-sessions, plain-start, plain-support, plain-tailwind, plain-toolbar, plain-tunnel, plain-vendor

Core modules: agents, assets, chores, cli, csrf, forms, http, logs, packages, preflight, runtime, server, signals, templates, test, urls, utils, views

Online docs URL pattern: `https://plainframework.com/docs/<pip-name>/<module/path>/README.md`

## CLI Quick Reference

- `uv run plain check` — run linting, preflight, migration, and test checks (add `--skip-test` for faster iteration)
- `uv run plain pre-commit` — `check` plus commit-specific steps (custom commands, uv lock, build)
- `uv run plain shell` — interactive Python shell with Plain configured (`-c "..."` for one-off commands)
- `uv run plain run script.py` — run a script with Plain configured
- `uv run plain request /path` — test HTTP request against dev database (`--user`, `--method`, `--data`, `--header`, `--status`, `--contains`, `--not-contains`)

## Debugging and verifying changes

Don't guess at errors — reproduce them first, read the traceback, then fix what it actually says.

- `uv run plain check` — lint, preflight, migration, and test checks in one shot (add `--skip-test` for faster iteration)
- `uv run plain request /path` — hit a view and see the full error/stacktrace (`--user`, `--status`, `--contains`, `--not-contains`)
- `uv run plain shell -c "..."` — run a quick snippet to test behavior in isolation
- `uv run plain test -x -k test_name` — run a specific failing test, stop on first failure
- `print()` statements — add them, run the code, read the output, then remove before committing
