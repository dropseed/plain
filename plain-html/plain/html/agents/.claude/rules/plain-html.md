---
paths:
  - "**/templates/**/*.html"
  - "**/*.py"
---

# HTML Templates

Templates are `.html` files under `templates/` (in your app or any installed package). One file per template/component — components are just templates you `:include`.

## Expressions

- Expressions are real Python in `{ ... }` — NOT `{{ ... }}` (that's Jinja). Double `{{` / `}}` is the literal-brace escape.
- No `|filter` syntax, no `{% block %}` / `{% macro %}` — call Python directly. Need a helper? Import it in frontmatter.
- `class` works as a normal attribute (`<div class={css}>`). Don't use `class_=` — that's a Jinja workaround and doesn't apply here.

## Directives (attribute form, prefixed with `:`)

- `:if={expr}` — conditional render. `<template :if={...}>...</template>` for no wrapping element.
- `:for={item in items}` — repeat element. Tuple unpacking works: `:for={(i, x) in enumerate(xs)}`.
- `:include="path/To/Component"` — literal string resolves at compile time. Expression form `:include={name}` resolves at render time. Children become the default slot; use `<template slot="name">` for named slots.

## Frontmatter

YAML between `---` fences at the top of the file. Three keys:

- `imports:` — list of import statements; run once at module load, visible in every `{expr}`.
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

- `uv run plain html check` — parse + validate every template (add `--typecheck` to run `ty` over `{expr}` against `attrs:` / `imports:`).
- `uv run plain html format` — canonicalize whitespace and attribute order in place. Use `--check` in CI.
- `uv run plain html compile` — pre-fill the on-disk cache (deploy-time warm).

## Cache location

The compile cache lives at `<project>/.plain/html/` (mode `0700`). Override the location with the `HTML_CACHE_DIR` setting; disable entirely with `HTML_CACHE_DISABLED = True`. Both accept Plain's standard `PLAIN_*` env-var overrides (`PLAIN_HTML_CACHE_DIR`, `PLAIN_HTML_CACHE_DISABLED`).

Run `uv run plain docs html` for full documentation.
