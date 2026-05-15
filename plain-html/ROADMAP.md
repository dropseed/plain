# plain.html — roadmap

Deferred, optional enhancements. The core engine, the repo-wide template
migration, and the `check` / `format` / `compile` tooling are all shipped;
these are follow-ups, not commitments.

# Component model

Gaps in the component model, drawn from a study of Phoenix HEEx. Ordered
roughly by effort-to-value.

## Global attribute pass-through

Today an undeclared attribute on a component tag is dropped (and flagged by
`componentcheck`). That makes wrapper components (`<Button>`, `<Card>`)
painful — they can't accept ambient `class` / `data-*` / `aria-*` without
declaring each one. Add a declared escape hatch in the spirit of HEEx's
`attr :rest, :global`: the component opts in to "accepts arbitrary
attributes," so it stays statically *known that* it takes globals without
enumerating which. Spread the collected attributes onto an element. Purely
additive — fully back-compatible to add later.

## Always-on structural component validation

`componentcheck` (unknown attr, missing required slot, etc.) runs only under
`plain html check`. It's cheap pure-Python — run it on every template
compile too, so a wrong component call fails at the moment it's written, not
in CI. HEEx does this as part of every compile.

## `:values` enum on `attrs:`

Let an `attrs:` declaration constrain a value to a literal set
(`size: str` allowing only `"small"` / `"large"`); `--typecheck` warns on a
literal outside the set. HEEx's `attr :size, values: ~w(small large)`.

## Richer slots — repeatable, attribute-carrying

Today a named slot is supplied once with no arguments. HEEx slots can be
supplied multiple times, and each entry carries its own attributes — that's
how tables / tabs / menus are built (the component owns iteration, the
caller owns per-item markup). This is the real feature gap. Ship repeatable
+ attribute-carrying slots first; treat `:let` (passing data from the
component back into the caller's slot markup) as a separate, harder
decision — it reintroduces caller-side scope binding.

## Static/dynamic compiled representation

The architectural bet, deferred until there's a consumer. The compiler emits
a flat `render() -> str`; HEEx instead keeps a tree of *static* segments and
*dynamic* holes. That split is the single primitive behind efficient
partial re-render and minimal-diff updates — the thing a serious hypermedia
layer in `plain-htmx` would want. Not worth building speculatively. The
current block syntax is already compatible with it; the one footgun to avoid
is relying on walrus (`:=`) bindings inside `{{ }}`, which would defeat
per-expression change tracking the way loose variables do in HEEx.

# Lint tiers

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
