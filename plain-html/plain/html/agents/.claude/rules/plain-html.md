---
paths:
  - "**/templates/**/*.html"
  - "**/*.py"
---

# HTML Templates

Templates are `.html` files under `templates/` (in your app or any installed package). One file per template/component — components are just templates invoked as PascalCase tags.

## Expressions

- Interpolate with `{{ ... }}` — real Python, NOT a DSL. No `|filter` syntax; call Python directly. Need a helper? Import it in frontmatter.
- Single `{` and `}` are ordinary text. For a literal `{{`, `{%`, or `{#`, wrap the region in `{% raw %}...{% endraw %}`.
- `class` works as a normal attribute (`<div class="{{ css }}">`). Don't use `class_=` — that's a Jinja workaround and doesn't apply here.

## Control flow (`{% %}` blocks)

Control flow is `{% %}` block tags — a visibly separate layer from HTML. Blocks are **HTML-aware**: every branch must contain balanced HTML.

- `{% if expr %}` / `{% elif expr %}` / `{% else %}` / `{% endif %}` — conditional chain.
- `{% for clause %}` / `{% endfor %}` — loop. Clause is a Python comprehension clause: one `for` plus any number of `if` filters (`{% for x in xs if x.visible %}`). Tuple unpacking works (`{% for (i, x) in enumerate(xs) %}`). Multiple `for` clauses are disallowed — nest a second `{% for %}`. There is no `{% empty %}` / `for`-`else`; render the empty case with `{% if not items %}`.
- `{% slot "name" %}` / `{% endslot %}` — caller-side, routes content to a component's named slot.
- `{# comment #}` — dropped from output (unlike `<!-- -->`, which is rendered).
- A **tag straddle** (`{% if %}<div>{% endif %}…</div>`) is a compile error — each branch must be balanced HTML. Vary the whole element with two branches, or extract a component.
- `{% %}` cannot appear inside a start tag. Conditional attributes use an expression value: `disabled="{{ is_disabled }}"` (a falsy value omits the attribute).

## Components

- Components are PascalCase tags. List each one under the `components:` frontmatter key, then invoke it: `<Card>...</Card>` or self-closing `<Card />`.
- Tag name = path's last segment (`components/Card` → `<Card>`); use `as Name` to rename (`base as Base`).
- Resolved tag name MUST be PascalCase. Lowercase tags are always plain HTML — you cannot shadow `<button>`.
- Layouts are ordinary components — no `extends` / `layout:`. Import the layout and render content inside it.

## Slots

- A component declares slots in `slots:` and reads them as bindings: `{{ children }}` is the default slot, named slots by their declared name.
- Caller: unmarked direct children fall through to the default slot; `{% slot "name" %}...{% endslot %}` routes content to a named slot.
- Required slot → `Markup`; optional slot not provided → `None`. Two `{% slot %}` blocks with the same name is a compile error.
- No parametric slots. Use composition.

## Frontmatter

YAML between `---` fences at the top of the file. Four keys:

- `imports:` — list of import statements; run once at module load, visible in every expression.
- `components:` — list of `path` or `path as Name` entries; templates to invoke as PascalCase tags.
- `attrs:` — declared inputs (`name: type` or `name: type = default`). Used at runtime AND by `plain html check --typecheck`.
- `slots:` — declared slot names (`name: required` / `name: optional`).

## Autoescape and `mark_safe`

Every `{{ expr }}` is escaped for its position (text, generic attr, URL attr scheme-allowlist, etc.). Event-handler attrs (`onclick=`) are a **compile error** for dynamic data — wrap in `mark_safe(...)` to opt in, or write a literal handler. `<script>` and `<style>` bodies are opaque — `{{ }}` is not parsed; pass data through a `data-*` attribute or a separate `<script type="application/json">` block.

`mark_safe(s)` and `Markup(s)` both wrap a string as a `SafeString` (emitted verbatim, no escape). Both are auto-imported into every compiled template — call either to opt out of escaping. Never call them on user input.

## Imports for views

View classes (`TemplateView`, `FormView`, `ListView`, `DetailView`, `CreateView`, `UpdateView`, `DeleteView`, `NotFoundView`) import from `plain.html`, not `plain.views`.

## CSP-safe shipped templates

In this repo's templates (admin, toolbar, packages), the same CSP rules apply as elsewhere: no inline `style="..."`, no inline event handlers, nonce on inline `<script>` / `<style>`. See the repo CLAUDE.md for the full list.

## CLI

- `uv run plain html check` — parse + validate every template (add `--typecheck` to run `ty` over expressions and component call sites against `attrs:` / `imports:` / `components:`).
- `uv run plain html format` — canonicalize whitespace and attribute order in place. Use `--check` in CI.
- `uv run plain html compile` — pre-fill the on-disk cache (deploy-time warm).

## Cache location

The compile cache lives at `<project>/.plain/html/` (mode `0700`). Override the location with the `HTML_CACHE_DIR` setting; disable entirely with `HTML_CACHE_DISABLED = True`. Both accept Plain's standard `PLAIN_*` env-var overrides (`PLAIN_HTML_CACHE_DIR`, `PLAIN_HTML_CACHE_DISABLED`).

Run `uv run plain docs html` for full documentation.
