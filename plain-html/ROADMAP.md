# plain.html — roadmap

Deferred, optional enhancements. The core engine, the repo-wide template
migration, and the `check` / `format` / `compile` tooling are all shipped;
these are follow-ups, not commitments.

Lint rules use a `PHxxx` code scheme with per-rule severity
(`error` / `warning` / `off`) configured under `[tool.plain.html]` in
`pyproject.toml`. `PH0xx` (syntax & structure) already ships as part of
`plain html check`.

## HTML content-model lint rules (`PH1xx`)

A second walker over the parsed tree — separate from the structural pass —
enforcing WHATWG content-model rules: `<p>` / `<a>` / `<button>` nesting,
`<table>` / `<ul>` / `<ol>` / `<dl>` structure, required attributes
(`<a href>`, `<img alt>`, `<input type>`), constrained attribute values
(`<input type>`, `<meta charset>`, `<link rel>`), and duplicate-id
detection. Each rule is `(code, severity, predicate)`; diagnostics reuse the
existing `file:line:col` shape.

plain.html wrinkles: the walker must descend `{% if %}` / `{% for %}` /
`{% slot %}` blocks transparently for nesting purposes; a dynamic
`id={{ expr }}` skips the duplicate-id check; a literal `id` inside a
`{% for %}` gets its own rule; `type={{ x }}` skips the enum check.

Vendor `html-validate`'s `html5.json` (MIT) as the content-model data.

## Accessibility lint rules (`PH2xx`)

Warnings by default, off-able per rule: `<img>` missing `alt`; `<button>`
with no accessible name; heading-level skips; invalid ARIA
role/attribute/value; `<input>` with no associated `<label>`. Vendor
`aria-query`'s role/attribute JSON.

## Expression-interior formatting

Run `ruff format` over `{{ }}` expression bodies during `plain html format`.
Extract every expression into a synthesized `.py` (reuse the typecheck
source map), run `ruff format --stdin-filename`, splice results back.
Idempotent by construction; cache by template content hash + ruff version.

## Tailwind class sorting

Opt-in via `[tool.plain.html] tailwind_sort = true`. Shell out to `rustywind`
as a `plain html format` post-pass over literal `class="..."` values; skip
any value containing `{{ expr }}`.
