# plain.html — authoring model (syntax redesign)

Status: design agreed, ready to implement.
Supersedes the syntax described in `plain-html/plain/html/README.md` and the
relevant phases of `plain-html-implementation-plan.md`. The engine already
exists; this is a change to the **authoring surface**, plus a migration of
every in-repo template.

## Summary of decisions

| Area                           | Decision                                                       |
| ------------------------------ | -------------------------------------------------------------- |
| Frontmatter                    | Stay YAML. Add a `components:` key.                            |
| Expressions                    | `{python}` — unchanged.                                        |
| Components                     | PascalCase tags `<Card>`, imported via a `components:` list.   |
| `<template :include>`          | **Removed entirely.** One way to invoke a component.           |
| Directives                     | `:if`, `:elif`, `:else`, `:for`, `:slot`.                      |
| `:for`                         | Takes a full Python comprehension clause (one `for` + N `if`). |
| Slots                          | Declared in `slots:`; provided caller-side via `:slot="name"`. |
| Parametric slots               | **Dropped.** No `:let`, no `yields:`. Use composition.         |
| HTML element override          | Not allowed — component tags must be PascalCase.               |
| `page:` global / `layout:` key | Not added. Layouts are ordinary components.                    |

## Why these (one line each, so we don't relitigate)

- **YAML frontmatter** — legible bounded contract; no execution-model footguns;
  consistent with `.md` frontmatter in plain-pages. Python frontmatter felt
  "slippery" (implicit contract, unbounded surface, import-time semantics).
- **PascalCase, not Phoenix `<.card>`** — maps to existing PascalCase filenames,
  familiar from React/Vue/Svelte/Astro, parses (lossily) in standard HTML tools.
  Dot-prefix is HTML-invalid and unfamiliar outside Elixir.
- **No HTML override** — React/Astro/Phoenix all draw this line; per-file
  shadowing of `<button>` makes every template require global context to read.
- **Drop `<template :include>`** — "one obvious way." Component tags cover it.
- **`:slot` directive, not `<:name>` tag or bare `slot=`** — `<:name>` overloads
  the colon into tag position (collides visually with `:else`); bare `slot=`
  would be the one non-colon attribute that's secretly consumed. `:slot` keeps
  the rule pure: every colon attribute is a directive, consumed and stripped.
- **Drop parametric slots** — the complexity (`:let`, `yields:`, slot-as-callable,
  closure compilation) only serves a use case that composition covers
  server-side. Re-addable additively later if a real forcing case appears.

## The authoring model

### Frontmatter (YAML, between `---` fences)

Recognized keys: `imports`, `components`, `attrs`, `slots`.

- **`imports:`** — list of Python `import` statements; run once at module load.
- **`components:`** — list of template paths to import as component tags.
  Default tag name is the path's last segment; `as Name` renames.
  The resolved name must be PascalCase. Collisions are a compile error.
- **`attrs:`** — declared inputs (`name: type` or `name: type = default`).
- **`slots:`** — declared slots (`name: required` / `name: optional`).

### Component invocation

```html
---
imports:
  - from app.models import Project
components:
  - components/Card
  - components/Button
  - base as Base
attrs:
  projects: list[Project]
slots:
  default: required
---

<Base>
  <h1 :slot="title">Projects</h1>

  <ul :if={projects}>
    <Card :for={p in projects if p.visible} title={p.name}>
      <p>{p.description}</p>
      <Button :slot="footer" href="/projects/{p.id}/">Open</Button>
    </Card>
  </ul>
  <p :else>No projects yet.</p>
</Base>
```

- Component tags are PascalCase and must be declared in `components:`.
- `<template :include>` no longer exists.
- Layouts are ordinary components — `base.html` imported `as Base`, used as
  `<Base>...</Base>`. No special `layout:` mechanism.

### Directives (colon-prefixed attributes — always attribute position)

- `:if={expr}` / `:elif={expr}` / `:else` — conditional chain. `:elif`/`:else`
  must be the next element sibling of their predecessor; only whitespace and
  HTML comments may sit between chain members.
- `:for={clause}` — repeat. Clause is a Python comprehension clause: one `for`
  plus any number of `if` filters. Tuple unpacking works
  (`:for={(i, x) in enumerate(xs)}`). Multiple `for` clauses are disallowed —
  nest `<template :for>` instead.
- `:slot="name"` — marks an element (caller-side) as content for a named slot.
  Literal string value (slot names are static). Works on any element.
- A conditional directive and `:for` on the **same element** is a compile error
  (gate a loop with `<template :if>`; filter with the `:for` clause).

### Slots

- Component declares slots in `slots:`. Reads them as bindings in the body:
  `{children}` is the default slot, `{header}` etc. are named.
- Required slot → `Markup`. Optional slot not provided → `None`.
- Caller provides content with `:slot="name"`; unmarked direct children fall
  through to the default slot. `<template :slot="name">` wraps multi-element
  content. Two elements with the same `:slot` value → compile error.

### `<template>` element

A real HTML element, used as a no-output wrapper for directives:
`<template :if>`, `<template :for>`, `<template :slot>`. This is its only role.

### Full vocabulary

```
<Tag>              PascalCase  → component (declared in components:)
<tag>              lowercase   → HTML element
<template>         HTML element → no-output directive container
:if :elif :else :for :slot  → directives (colon = plain.html, attribute position)
{expr}             → Python expression (body or attribute value)
{{  }}             → literal brace escape
```

Every colon is a directive; every directive is a colon; every directive is in
attribute position. No tag-position colon, no secretly-consumed bare attribute.

## Open items (decide during implementation)

1. **plain-support dynamic includes** (4 sites in `support/page.html` +
   `support/iframe.html`). DECIDED: **view-level dispatch (A)**. The
   plain-support view resolves the app-configured template, renders it to
   `Markup`, and passes the result into `page.html` / `iframe.html` as an attr.
   The templates become fully static. This preserves the invariant that a
   plain.html template's set of sub-templates is statically knowable at
   compile time — no dynamic-render primitive is added.
2. **plain-pages alignment** — plain-pages stays a file router + markdown +
   redirects + asset passthrough. Its `page.html` wrapper migrates to `<Base>`.
   No `page:` global; page metadata flows as ordinary attrs/slots.
3. **Self-closing `<Card />`** — parser must accept self-closing component tags
   (HTML5 only self-closes void elements).
4. **Typecheck integration** — `components:` imports must be visible to the
   `plain html check --typecheck` pass so component attrs are checked at call
   sites.

## Migration scope

- 59 files, 243 `:include` sites → component tags + `components:` declarations.
- 23 `slot=` sites → `:slot="name"`.
- 4 dynamic `:include={}` sites (plain-support) → see open item 1.
- Targets: `example/`, `plain-admin`, `plain-toolbar`, `plain-support`,
  `plain-pages`, and any other in-repo package shipping templates.
- The `plain html format` tool can likely automate the mechanical
  `:include` → component-tag and `slot=` → `:slot=` transforms.

## Implementation order (suggested)

1. Parser/compiler: `components:` frontmatter key + PascalCase tag resolution.
2. Parser/compiler: `:elif` / `:else` chain; `:for` comprehension-clause filter.
3. Parser/compiler: `:slot` directive; remove `<template :include>` + parametric
   slot machinery (`:let`, `yields:`).
4. Typecheck pass: component-tag call-site checking.
5. Resolve plain-support dynamic includes (open item 1).
6. Migrate in-repo templates; run the parity/conformance suite.
7. Update `plain-html/plain/html/README.md` and the package agent rule.
