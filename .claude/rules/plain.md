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
- **Model options**: Use `model_options = models.Options(...)` not `class Meta`. Fields don't accept `unique=True` — use `UniqueConstraint` in constraints.
- **CSRF**: Automatic header-based (Sec-Fetch-Site). No tokens in templates — no `{{ csrf_input }}` or `{% csrf_token %}`.
- **Forms**: Headless — no `as_p()`, `as_table()`, or `as_elements()`. Render fields manually with `form.field.html_name`, `form.field.html_id`, `form.field.value()`, `form.field.errors`.
- **Middleware**: No `AuthMiddleware` exists. Auth works through sessions + view-level checks (`AuthViewMixin`). Middleware uses short imports (`plain.admin.AdminMiddleware` not `plain.admin.middleware.AdminMiddleware`).

When in doubt, run `uv run plain docs <package> --api` to check the actual API.

## Documentation

**Discovery** — find what's available and where things are:

- `uv run plain docs --list` — all packages and core modules with descriptions
- `uv run plain docs --outline` — section headings for all installed docs
- `uv run plain docs <name> --outline` — section headings (with `###` subsections) for one module
- `uv run plain docs --search <term>` — find which modules/sections mention a term (compact, one line per section)
- `uv run plain docs --search <term> --api` — also search public API symbols (class/function names), not just docs

**Reading** — get full content:

- `uv run plain docs <name>` — full markdown docs
- `uv run plain docs <name> --section <name>` — one specific `##` section
- `uv run plain docs <name> --search <term>` — full content of all matching sections in that module
- `uv run plain docs <name> --search <term> --api` — also include matching API symbols in search results
- `uv run plain docs <name> --api` — public API surface (classes, functions, signatures)

**Workflow**: Use `--search <term>` to find which module has what you need, then `<name> --search <term>` to get the full sections, or `<name> --section <name>` for a specific one. Add `--api` to search if looking for a class or function name that might not appear in docs prose.

Packages: plain, plain-admin, plain-api, plain-auth, plain-cache, plain-code, plain-dev, plain-elements, plain-email, plain-esbuild, plain-flags, plain-htmx, plain-jobs, plain-loginlink, plain-models, plain-oauth, plain-observer, plain-pages, plain-pageviews, plain-passwords, plain-pytest, plain-redirection, plain-scan, plain-sessions, plain-start, plain-support, plain-tailwind, plain-toolbar, plain-tunnel, plain-vendor

Core modules: agents, assets, chores, cli, csrf, forms, http, logs, packages, preflight, runtime, server, signals, templates, test, urls, utils, views

Online docs URL pattern: `https://plainframework.com/docs/<pip-name>/<module/path>/README.md`

## CLI Quick Reference

- `uv run plain check` — run linting, preflight, migration, and test checks (add `--skip-test` for faster iteration)
- `uv run plain pre-commit` — `check` plus commit-specific steps (custom commands, uv lock, build)
- `uv run plain shell` — interactive Python shell with Plain configured (`-c "..."` for one-off commands)
- `uv run plain run script.py` — run a script with Plain configured
- `uv run plain request /path` — test HTTP request against dev database (`--user`, `--method`, `--data`, `--header`, `--status`, `--contains`, `--not-contains`)
- `uv run plain settings list` — list all settings with their current values and sources
- `uv run plain settings get <SETTING_NAME>` — get the value of a specific setting

## Views

- Don't evaluate querysets at class level — queries belong in view methods
- Always paginate list views — unbounded queries get slower as data grows
- Wrap multi-step writes in `transaction.atomic()`

Run `uv run plain docs views --section "view-patterns"` for full patterns with code examples.

## Security

- Validate at form/model level, not just in views
- Never format raw SQL strings — always use parameterized queries
