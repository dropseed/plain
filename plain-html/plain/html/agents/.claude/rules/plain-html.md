---
paths:
  - "**/templates/**/*.html"
  - "**/*.py"
---

# HTML Templates

Templates are `.html` files under `templates/` (in your app or any installed package). One file per template/component — components are just templates invoked as PascalCase tags.

## Expressions

- Expressions are real Python in `{ ... }` — NOT `{{ ... }}` (that's Jinja). Double `{{` / `}}` is the literal-brace escape.
- No `|filter` syntax, no `{% block %}` / `{% macro %}` — call Python directly. Need a helper? Import it in frontmatter.
- `class` works as a normal attribute (`<div class={css}>`). Don't use `class_=` — that's a Jinja workaround and doesn't apply here.

## Directives (attribute form, prefixed with `:`)

Every colon attribute is a directive — consumed and stripped, never rendered. The set is `:if`, `:elif`, `:else`, `:for`, `:slot`.

- `:if={expr}` / `:elif={expr}` / `:else` — conditional chain. `:elif` / `:else` must be the next element sibling of their predecessor (only whitespace/comments between). `<template :if={...}>...</template>` for no wrapping element.
- `:for={clause}` — repeat element. Clause is a Python comprehension clause: one `for` plus any number of `if` filters (`:for={x in xs if x.visible}`). Tuple unpacking works (`:for={(i, x) in enumerate(xs)}`). Multiple `for` clauses are disallowed — nest `<template :for>`.
- A conditional directive and `:for` on the **same element** is a compile error — gate a loop with `<template :if>`, filter items with the `:for` clause's `if`.
- `:slot="name"` — caller-side, marks an element as content for a named slot. Literal string value. Use `<template :slot="name">` to group multiple elements.

## Components

- Components are PascalCase tags. List each one under the `components:` frontmatter key, then invoke it: `<Card>...</Card>` or self-closing `<Card />`.
- Tag name = path's last segment (`components/Card` → `<Card>`); use `as Name` to rename (`base as Base`).
- Resolved tag name MUST be PascalCase. Lowercase tags are always plain HTML — you cannot shadow `<button>`.
- There is no `<template :include>` — that syntax is removed. Component tags are the only way to invoke a component.
- Layouts are ordinary components — no `extends` / `layout:`. Import the layout and render content inside it.

## Slots

- A component declares slots in `slots:` and reads them as bindings: `{children}` is the default slot, named slots by their declared name.
- Caller: unmarked direct children fall through to the default slot; `:slot="name"` routes content to a named slot.
- Required slot → `Markup`; optional slot not provided → `None`. Two elements with the same `:slot` value is a compile error.
- No parametric slots — no `:let`, no `yields:`. Use composition.

## Frontmatter

YAML between `---` fences at the top of the file. Four keys:

- `imports:` — list of import statements; run once at module load, visible in every `{expr}`.
- `components:` — list of `path` or `path as Name` entries; templates to invoke as PascalCase tags.
- `attrs:` — declared inputs (`name: type` or `name: type = default`). Used at runtime AND by `plain html check --typecheck`.
- `slots:` — declared slot names (`name: required` / `name: optional`).

## Autoescape and `mark_safe`

Every `{expr}` is escaped for its position (text, generic attr, URL attr scheme-allowlist, etc.). Event-handler attrs (`onclick=`) are a **compile error** for dynamic data — wrap in `mark_safe(...)` to opt in, or write a literal handler. `<script>` and `<style>` bodies are opaque — `{expr}` is not parsed; pass data through a `data-*` attribute or a separate `<script type="application/json">` block.

`mark_safe(s)` and `Markup(s)` both wrap a string as a `SafeString` (emitted verbatim, no escape). Both are auto-imported into every compiled template — call either to opt out of escaping. Never call them on user input.

## Imports for views

View classes (`TemplateView`, `FormView`, `ListView`, `DetailView`, `CreateView`, `UpdateView`, `DeleteView`, `NotFoundView`) import from `plain.html`, not `plain.views`.

## CSP-safe shipped templates

In this repo's templates (admin, toolbar, packages), the same CSP rules apply as elsewhere: no inline `style="..."`, no inline event handlers, nonce on inline `<script>` / `<style>`. See the repo CLAUDE.md for the full list.

## CLI

- `uv run plain html check` — parse + validate every template (add `--typecheck` to run `ty` over `{expr}` and component call sites against `attrs:` / `imports:` / `components:`).
- `uv run plain html format` — canonicalize whitespace and attribute order in place. Use `--check` in CI.
- `uv run plain html compile` — pre-fill the on-disk cache (deploy-time warm).

## Cache location

The compile cache lives at `<project>/.plain/html/` (mode `0700`). Override the location with the `HTML_CACHE_DIR` setting; disable entirely with `HTML_CACHE_DISABLED = True`. Both accept Plain's standard `PLAIN_*` env-var overrides (`PLAIN_HTML_CACHE_DIR`, `PLAIN_HTML_CACHE_DISABLED`).

Run `uv run plain docs html` for full documentation.
