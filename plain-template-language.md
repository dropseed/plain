# Plain template language — design specification

A consolidated specification of the template language design that emerged from the frontend-rethink research arc. This is the *what*; implementation strategy is a separate future.

## Goal

Design the minimum template language that:

- Makes server-rendered HTML the default mode of authoring UI in Plain
- Is statically checkable end-to-end (HTML structure + embedded Python expressions + component call sites + form-field binding contracts)
- Stays painfully obvious — every operation visible from the call site, no magical resolution
- Is XSS-safe by construction via contextual autoescape
- Reads like HTML, not like a separate language embedded in HTML

Plain's priority has shifted from human-familiarity-first to agent-authored-first. Static verifiability matters more than ecosystem familiarity. The template language is being designed for that posture.

## Design principles

1. **The template engine does what only HTML-aware engines can do; Python does everything else.** No filters, no `endif`, no `{% set %}`, no template inheritance, no macros, no autoescape opt-outs — Python expressions, methods, comprehensions, and helpers cover those needs natively.
2. **Components are template files, not Python objects.** No registry, no decorators, no Python imports for templates. Just files at paths invoked from other files.
3. **Static checking is the verification layer.** `plain template check` runs structural validation + type checks against extracted expressions, with errors mapped back to template positions.
4. **Contextual autoescape, no opt-out.** Where a value lands (text body, attribute, URL, JS, CSS) determines its escape policy. The engine knows; the author doesn't need to.
5. **Align with HTML / Web Components specs where they exist.** `<template>`, `slot=`, attribute semantics — use what HTML already defines rather than invent parallels.
6. **One way to do things.** No `<.component>` *and* `<my-component>` *and* `<template :include>`. Pick one. (We picked the third.)

## File format

A Plain template file has two sections separated by `---` fences:

```html
---
# YAML frontmatter declaring this template's contract
attrs:
  user: app.presenters.UserPresenter
  show_details: bool = False
slots:
  default: required
  header: optional
---
<!-- Template body — HTML with engine-aware extensions -->
<article>
  <h2 :if={user.is_verified}>{user.display_name}</h2>
  ...
</article>
```

File extension: `.plain` initially (to coexist with `.html` Jinja during migration). Long-term may become the default `.html` once Jinja is retired.

## Frontmatter

YAML-only. Two sections:

### `attrs:`

Declares the typed inputs this template accepts. Two forms:

**Inline (simple cases)** — `name: type-expression` with optional `= default`:

```yaml
attrs:
  user: app.presenters.UserPresenter
  form: app.forms.UserEditForm
  show_details: bool = False
  count: int = 0
  recent_users: list[app.users.models.User] = []
  fallback: str | None = None
  size: Literal["sm", "md", "lg"] = "md"
  variant: Literal["primary", "danger", "success"] = "primary"
```

**Expanded (with metadata)** — nested dict when documentation or examples are useful:

```yaml
attrs:
  field:
    type: plain.forms.fields.FormField
    required: true
    doc: The form field this input is bound to.
    examples: [form.email, form.password]
  variant:
    type: Literal["primary", "danger", "success"]
    default: primary
    doc: Visual treatment for the button.
```

**Type expressions are real Python type-hint syntax.**

- Built-ins unqualified: `int`, `str`, `bool`, `list`, `dict`, `float`, `bytes`, `None`
- Other types fully-qualified: `app.presenters.UserPresenter`
- Generics: `list[X]`, `dict[K, V]`, `tuple[A, B]`
- Unions: `X | None`, `int | str`
- Optional: `X | None` (PEP 604) or `Optional[X]`
- Enum constraints: `Literal["a", "b", "c"]` (instead of inventing a `values:` field — Python's type system already does this and ty/pyright validate it natively)
- Attribute-spread bag: `dict[str, str]` for the `{**rest}` pattern

The static checker parses each value with `ast.parse(..., mode='eval')`, resolves dotted names via Python's import system, and uses the resulting types as the scope for expression checking in the template body.

### `imports:` (optional)

Brings non-attr names into the template's expression scope. Used for helpers, constants, and free-standing functions referenced inside `{...}` expressions.

```yaml
imports:
  - from app.helpers import format_date, currency
  - from datetime import datetime
  - from plain.utils.text import truncate
```

Each item is a Python import statement. At compile time, these become real imports at the top of the generated render function's module. At check time, the same imports populate the synthesized checker module so expressions like `{format_date(user.created_at)}` resolve correctly.

**This is the only place templates declare value-level dependencies.** Type references inside `attrs:` are auto-resolved by their fully-qualified path (no explicit import needed); `imports:` is specifically for *callable* and *value* names needed inside the template body.

### `slots:`

Declares the slots this template accepts. Each entry is `name: required | optional`.

```yaml
slots:
  default: required
  header: optional
  footer: optional
  actions: optional
```

`default` is the unnamed slot (loose children of the call site). Named slots correspond to elements with a matching `slot=` attribute (or `<template slot=>` wrappers) in the calling context.

If a slot is `required`, omitting it at a call site is a check-time error. If `optional`, the template body can reference it conditionally with `:if`.

## Template body — engine-aware features

The body is HTML with six engine-aware extensions:

### `{python_expr}` — interpolation

A Python expression inside `{}` is evaluated and interpolated at render time, with contextual autoescape based on its position.

```html
<p>Hello, {user.name}!</p>
<a href={user.profile_url}>Profile</a>
<button disabled={form.processing}>Save</button>
<div class={["card", "is-verified" if user.is_verified else None]}>
```

Allowed in: text body, attribute values, attribute lists (`class={[...]}`), attribute splats (`{**kwargs}`), boolean attributes.

The expression is *any* Python expression — including ternaries, comprehensions, method calls, attribute access, arithmetic. f-string-grade expressiveness.

### `:if={cond}` — element-level conditional

A `:if={expression}` attribute on any element controls whether that element (and its descendants) render.

```html
<span :if={user.is_admin} class="badge">admin</span>
<aside :if={show_sidebar}>...</aside>
```

The expression is a Python expression evaluated for truthiness. Element-level only — there are no block-form conditionals.

For multi-element conditionals, wrap in a real container (`<section>`, `<div>`, etc.) or use `<template :if={...}>` for a wrapper-free fragment.

### `:for={x in xs}` — element-level iteration

A `:for={target in iterable}` attribute renders the element once per item.

```html
<li :for={post in user.recent_posts}>
  <a href={post.url}>{post.title}</a>
</li>
```

The expression after `:for=` is a real Python for-clause — supports tuple unpacking, multi-target iteration, etc. (Whatever `ast.parse(..., mode='exec')` accepts.)

```html
<tr :for={(name, value) in user.attributes.items()}>
  <td>{name}</td>
  <td>{value}</td>
</tr>
```

### `<template :include="path">` — invoke another template

The canonical syntax for including another template with attrs and slot content.

```html
<template :include="forms/input_field" field={form.email} label="Email" />

<template :include="layouts/card" title="Profile">
  <p>Body content goes to the default slot.</p>
</template>
```

- Path is absolute from the configured templates root by default
- Leading `./` or `../` opts into relative-to-calling-template resolution
- Self-closing when there are no children (`<template :include="x" prop={v} />`)
- All non-directive attributes on `<template :include>` are passed as attrs to the included template
- Attrs are validated at check time against the included template's `attrs:` declarations

Restricted to `<template>` only. `<div :include="x">` is a parse error — wrap an `<template :include>` in a div if you want a wrapper.

### `<template>` and `slot="name"` — slot composition

**`slot="name"` attribute** routes an element's content to a named slot in the calling component. Web Components spec convention.

```html
<template :include="layouts/card" title="Profile">
  <h2 slot="header">{user.display_name}</h2>

  <footer slot="actions">
    <button>Edit</button>
  </footer>

  <p>Body content — goes to the default slot since it has no `slot` attribute.</p>
</template>
```

**`<template slot="name">`** wraps slot content that doesn't have a natural HTML element:

```html
<template :include="layouts/card">
  <template slot="header">Just text — no semantic wrapper needed</template>
  <p>Body content</p>
</template>
```

The `<template>` wrapper doesn't render; its children flow into the named slot.

Inside the included template, slots are accessed as `{children}` (default slot) or by their declared name (`{header}`, `{actions}`).

### `:as={var}` — scoped slots (the render-prop pattern)

A slot can receive a value from the parent template and bind it to a name for the slot's body. The receiving directive is `:as={name}`, following Python's `with x as y` and `import x as y` binding patterns.

```html
<template :include="components/table" rows={users}>
  <template slot="col" :as={user} label="Name">{user.name}</template>
  <template slot="col" :as={user} label="Email">{user.email}</template>
</template>
```

Inside `components/table.plain`, the slot is invoked once per row with the row value passed through:

```html
<!-- components/table.plain -->
---
attrs:
  rows: list[Any]
slots:
  col:
    required: true
    yields: Any  # the type of the value yielded to slot bodies
---
<table>
  <thead>
    <tr><th :for={c in col_slots}>{c.label}</th></tr>
  </thead>
  <tbody>
    <tr :for={row in rows}>
      <td :for={c in col_slots}>{c.render(row)}</td>
    </tr>
  </tbody>
</table>
```

The slot's `:as={var}` binding works identically whether the parent yields once (single-value slot like a title) or N times (per-row slot like a column).

**Why `:as` and not `:let`?** `:let` is Vue/Svelte/Angular vocabulary borrowed by HEEx. `as` is Python's actual binding keyword — already used for `with x as y`, `import x as y`, `except X as y`. Same shape, native vocabulary.

### `<template>` — fragments (no `:include`)

A `<template>` element without `:include` is a fragment — engine-processed, doesn't render as itself. Useful for multi-element groupings under `:if` or `:for` without adding a wrapper element.

```html
<template :if={show_details}>
  <dl>...</dl>
  <ul>...</ul>
</template>

<template :for={user in users}>
  <h3>{user.name}</h3>
  <p>{user.bio}</p>
</template>
```

## HTML-aware attribute semantics

Attribute values containing `{...}` expressions are evaluated with HTML-aware rules:

**Boolean attributes**: `true` renders the attribute name with no value; `false`/`None` omits the attribute entirely.

```html
<input required={field.required} />
<!-- if field.required is True: <input required>
     if False: <input> -->
```

**Class lists**: `class={list}` accepts a Python list, flattens, drops falsy entries.

```html
<div class={["card", elevated and "shadow", error and "border-danger"]}>
<!-- flattens and drops False/None — "card" always, others conditionally -->
```

**Attribute spread**: `{**dict}` inside a tag spreads a dict of attributes.

```html
<button {**extra_attrs} type="submit">Save</button>
```

Standard Python `**` splat operator. The dict's keys become attribute names; values follow the boolean/list rules above.

## Contextual autoescape

The engine knows where each expression sits and applies the correct escape policy automatically. No `|safe`, no `mark_safe()` calls in templates, no opt-out syntax.

| Position | Escape policy |
|---|---|
| Text body (`<div>{x}</div>`) | HTML-escape |
| Attribute value (`<a class={x}>`) | HTML-escape, attribute-safe |
| `href`, `src`, `formaction` attributes | URL-validate (reject `javascript:`, `data:` text/html, etc.), then HTML-escape |
| `<script>` body | Refuse (compile error — embedding values in scripts requires explicit opt-in via a helper) |
| `<style>` body | Refuse (compile error — same reason) |
| Boolean attribute value | Coerce to presence/absence |

If a value needs to bypass escaping, the Python side wraps in `Markup(...)` from `plain.utils.safestring` (or equivalent). The template engine has no in-template opt-out.

## Explicit policies for edge-case content

Lessons from HEEx's open issues — declaring these upfront avoids the corner-case drift Phoenix has been working through for years.

### `<script>` and `<style>` bodies

Treated as **opaque raw text**. No `{expr}` recognition. No attempt to parse the contents. If you need to interpolate a server-side value into JavaScript, do it via a `data-*` attribute on a regular element and read it from JS:

```html
<!-- Won't work, won't compile -->
<script>const userId = {user.id};</script>

<!-- Do this instead -->
<div data-user-id={user.id} id="page-state"></div>
<script src="/static/app.js"></script>
<!-- app.js reads document.getElementById('page-state').dataset.userId -->
```

This matches Go's `html/template` stance, matches Plain's CSP-strict posture, and avoids the entire "server data in JavaScript context" XSS class.

### HTML comments

`<!-- ... -->` passes through verbatim. No `{expr}` interpolation inside. If you find yourself wanting a dynamic HTML comment, you almost certainly don't — it's a smell.

`{# ... #}` is the template-only comment form; stripped at compile time, never reaches output. Two syntaxes, two purposes, no ambiguity.

### Inline SVG and namespaced attributes

`<svg>` and its descendants tokenize in a slightly looser mode. Namespaced attributes like `xmlns:custom` or `xlink:href` pass through without validation. The engine's contextual-autoescape rules still apply for interpolated values inside SVG attributes.

### Custom-namespaced HTML

`xmlns:custom="..."` and custom-namespaced tags (`<custom:thing>`) — also pass through. The tokenizer doesn't validate the namespace; expressions inside continue to use the surrounding context's escape policy.

## Type checking — what `plain template check` enforces

1. **HTML structural validation**: tag balance, void elements (no children for `<input>`, `<br>`, etc.), attribute name validity, correctly nested `<template>` and slot constructs.
2. **Expression type checking**: every `{}` expression in the template runs through ty (or pyright) against a synthesized scope built from the template's `attrs:`. Errors map back to template line:column.
3. **Include validation**: `<template :include="path">` resolves to an existing template file; attributes passed match the target's `attrs:` declarations (required attrs present, types compatible).
4. **Slot validation**: slot content matches the target's `slots:` declarations (required slots provided, no unknown slot names).
5. **Directive validation**: `:if`/`:for` expression types are boolish / iterable respectively.

Failure modes are check-time, mapped to template positions, runnable as a CLI (`plain template check <path>` or `plain template check --all`) or as a step in `plain check`.

## HTML correctness — beyond structural validation

Because the design's pitch is "Python in your HTML," HTML correctness is load-bearing, not optional. Agent-authored templates can produce structurally valid (closed tags) but semantically broken HTML — `<p><div></div></p>`, `<a>` nesting, `<button>` containing interactive content, duplicate `id`s, missing `alt` attributes. That's exactly the bug class agent-authoring introduces.

`plain template check` should grow into a real HTML linter, not just a type-and-structure checker. Roadmap in three tiers:

### Tier 1 — structural (v1)

Listed above. Tag balance, void elements, well-formed attributes, `:include` resolution, slot routing, directive types.

### Tier 2 — content model (mechanical, high-value)

WHATWG content-model rules. The spec is finite (~50 element rules); the work is mechanical:

- **Nesting rules**: `<p>` only contains phrasing content; `<a>` can't nest; `<button>` can't contain interactive content; `<table>` requires `<tbody>`/`<tr>`/`<td>` structure; `<ul>`/`<ol>` only contain `<li>`; `<dl>` only contains `<dt>`/`<dd>`; `<head>` only contains metadata elements.
- **Required attributes**: `<img alt>` (warning, since `alt=""` is valid for decorative images); `<a href>`; `<input type>`; `<form method>` and `<form action>` for non-GET.
- **Attribute value validity**: `<input type="...">` against the allowed set; `<meta charset>`; `<link rel>`.
- **Duplicate IDs** within a single template's rendered output.

### Tier 3 — accessibility (configurable, judgment-needed)

- Heading hierarchy: no `<h3>` before `<h1>`, no skipped levels
- Accessible names on `<button>` (text content, `aria-label`, or `aria-labelledby`)
- ARIA attribute validity (roles, states, properties against the ARIA spec)
- Form labels (every input has an associated `<label>`)

These are heuristics with false positives — warnings by default, off-able per rule.

### Configuration model

Same shape as ruff for Python. Per-rule severity in project config:

```toml
[tool.plain.template-check]
rules = "all"  # or a list

[tool.plain.template-check.rules]
"html-content-model" = "error"
"html-required-attrs" = "warning"
"a11y-heading-hierarchy" = "off"
"a11y-button-accessible-name" = "warning"
```

### Implementation strategy

- **html5lib's validation modes** cover much of Tier 1 and some of Tier 2 — Python-native, well-maintained
- **Hand-rolled WHATWG content-model rules** for the rest of Tier 2 — finite, mechanical (1000–1500 lines)
- **W3C Nu Html Checker** as an optional deep-check backend for CI (Java subprocess; slow but exhaustive). Optional, not default.

The progression from "type checker for embedded Python" to "linter for HTML + Python" is what makes the "Python in your HTML" pitch credible. Without HTML correctness, the static-checking story has a glaring gap.

## Extensibility — closed by design, integrate via Python

The template language has no extension or plugin system. The set of directives, tags, and frontmatter sections is fixed. Third-party packages integrate through two existing mechanisms:

1. **`imports:` brings Python helpers into the expression scope.** A package like plain.react ships Python functions (`from plain.react.template import react_mount`); users import them in their template frontmatter and call them as expressions.
2. **Component templates ship in package `templates/` directories.** Plain's existing template loader picks them up via the configured `TEMPLATE_DIRS`. Users include them with `<template :include="components/...">`.

The closed-language stance is a feature: reading any Plain template, the reader knows exactly what every directive means. There's no "this template depends on ext_X which adds `:something`" surprise. Same property as Go's standard library or Python's grammar — bounded surface, no third-party customization at the syntax level.

### Example: React integration

The plain.react package ships:

```html
<!-- plain/react/templates/components/react/mount.plain -->
---
imports:
  - from plain.react.template import serialize_props
attrs:
  component: str
  data: dict[str, Any] = {}
---
<div
  data-react-component={component}
  data-react-props={serialize_props(data)}
></div>
```

And helpers:

```python
# plain/react/template.py
def react(component: str, **data) -> Markup:
    """Convenience helper returning a React mount point as Markup."""
    return Markup(...)
```

User code:

```html
---
imports:
  - from plain.react.template import react
attrs:
  user: app.presenters.UserCardData
---
<!-- Via component template -->
<template :include="components/react/mount"
          component="UserCard"
          data={{"id": user.id, "name": user.name}} />

<!-- Or via helper -->
{react("UserCard", id=user.id, name=user.name)}
```

Both forms work; both are achieved with zero engine extension points. The same pattern applies to any other third-party integration (htmx-style attributes, admin macros, UI libraries) — package ships Python helpers and template files, users import what they need.

## Template resolution

Jinja-style `FileSystemLoader` semantics:

```python
TEMPLATE_DIRS = [
    "app/templates",            # app overrides win
    "plain.admin/templates",    # framework defaults
    "vendor_pkg/templates",     # third-party fallback
]
```

- **Absolute paths** (no leading `./`): looked up across `TEMPLATE_DIRS` in order. First match wins. This is how overrides work — your `app/templates/admin/header.plain` shadows `plain.admin/templates/admin/header.plain`.
- **Relative paths** (`./foo` or `../foo`): resolved relative to the calling template's directory. Used for "private partials" tied to a single page (Rails `_form_fields` pattern).

Same mental model Plain users already have for Jinja includes. No new framework conventions specific to components.

## Aliases — explicitly not in v1

We considered per-file aliases (`components:` or `include:` block in frontmatter mapping local names to paths, like Python imports for templates). HEEx, Astro, JSX, Vue, Svelte all do this.

Decision: not in v1. Every call site shows its full path. The verbosity cost is bounded (3-10 invocations per template is typical) and the explicit-path-at-call-site is genuinely useful for reading. If real apps reveal verbosity is hurting more than helping (specifically: same path repeated 5+ times in a single template), add aliases as a non-breaking sugar layer that desugars to `<template :include>`.

## What this deliberately doesn't have

| Feature | Why we don't have it |
|---|---|
| `{% endif %}`, `{% endfor %}` | No block forms — element-level directives only. The element's close tag is the natural terminator. |
| Filters (`{{ x \| upper }}`) | Python methods do this already: `{x.upper()}`. The pipe syntax was a workaround for languages without method-call access. |
| `else` / `elif` on `:if` | Use sibling `:if` directives with negated conditions, or Python ternaries inside `{}` when it's a value choice. |
| Template inheritance (`{% extends %}` + `{% block %}`) | Layouts are components with slots. One concept covers both reuse cases. |
| `{% set %}` for locals | Compute in the presenter. (Python's walrus operator covers the rare in-expression case.) |
| `{% include %}` (separate from components) | `<template :include>` is the include. |
| Macros (separate from components) | Components are the reusable unit. |
| `\|safe`, autoescape toggles | Contextual autoescape only. To emit raw HTML, wrap in `Markup()` on the Python side. |
| `<.component>` dot-syntax | Required name resolution (registry, import, or filesystem convention) that fights the "components are just files" model. |
| Per-file aliases | Not in v1 — explicit path at every call site. Reconsider if verbosity proves painful. |
| Web Components custom-element tags (`<my-card>`) | Implies runtime registration semantics that don't apply server-side. Borrowing the syntax without the semantics confuses readers. |
| Python-side component classes | Components are template files. No `class Card(Component)` anywhere. |
| Component registry (anywhere) | Files at paths; no name-to-thing mapping infrastructure. |
| Indentation-significant body | HTML is whitespace-insensitive; forcing template-body indentation rules mixes two whitespace philosophies in one file. |
| Logic inside components | Components are pure projections. Computation lives in presenters; presenters are passed as attrs. |

## Full syntax reference (one table)

| Construct | Purpose |
|---|---|
| `---\n...\n---` | YAML frontmatter fence |
| `attrs: { name: type }` | Declare typed inputs (inline or nested-with-metadata) |
| `imports:` | Bring non-attr names (helpers, constants) into the expression scope |
| `slots: { name: required\|optional }` | Declare accepted slots |
| `{python_expr}` | Interpolate Python expression (contextually autoescaped) |
| `:if={cond}` | Element-level conditional |
| `:for={target in iterable}` | Element-level iteration |
| `:as={name}` | Scoped slot binding — bind yielded value to `name` |
| `<template :include="path" prop={v}>` | Invoke another template with attrs |
| `slot="name"` (attribute) | Route element content to a named slot |
| `<template slot="name">` | Wrap slot content without a natural element |
| `<template>` (no attrs) | Fragment — group children without rendering wrapper |
| `class={list}` | List-flatten, drop falsy |
| `{**dict}` | Attribute splat |
| `attr={bool}` | Boolean attribute presence |
| `{# comment #}` | Template-only comment (stripped) |
| `<!-- comment -->` | HTML comment (preserved verbatim) |
| `Literal[...]` (in attrs) | Enum constraint via Python's typing module |

## End-to-end example

```html
<!-- app/templates/pages/users/edit.plain -->
---
attrs:
  user: app.presenters.UserPresenter
  form: app.forms.UserEditForm
---
<template :include="layouts/app" title="Edit user">
  <nav slot="nav">
    <a href="/users">← Users</a>
  </nav>

  <form method="post" action="/users/{user.id}/edit">
    <template :include="./form_fields" form={form} />
    <template :include="forms/submit">Save changes</template>
  </form>
</template>
```

```html
<!-- app/templates/pages/users/form_fields.plain -->
---
attrs:
  form: app.forms.UserEditForm
---
<template :include="forms/input_field" field={form.email} label="Email" />
<template :include="forms/input_field" field={form.name} label="Name" />
<template :include="forms/select_field" field={form.role} label="Role" />
<template :include="forms/checkbox_field" field={form.is_active} label="Active" />
```

```html
<!-- app/templates/forms/input_field.plain -->
---
attrs:
  field: plain.forms.fields.FormField
  label: str = ""
  type: str = "text"
  help: str = ""
---
<div class="space-y-1">
  <label for={field.html_id}>{label}</label>
  <input
    id={field.html_id}
    name={field.html_name}
    type={type}
    value={field.value() or ""}
    required={field.field.required}
    aria-invalid={bool(field.errors)}
  />
  <p :if={help} class="text-sm text-muted">{help}</p>
  <p :for={error in field.errors} class="text-sm text-danger">{error}</p>
</div>
```

## Migrating from Jinja

Every Jinja feature we care about either maps directly, translates to a Python expression, or pushes a concern to the presenter layer.

### Direct translations

| Jinja | Plain | Notes |
|---|---|---|
| `{{ x }}` | `{x}` | Single-brace, contextually autoescaped |
| `{% if x %}<a/>{% endif %}` | `<a :if={x} />` | Element-level directive |
| `{% for x in xs %}<li>{{x}}</li>{% endfor %}` | `<li :for={x in xs}>{x}</li>` | Same shape |
| `{% include "x.html" %}` | `<template :include="x" />` | Self-closing when no children |
| `{% from "x" import macro %}` + `{{ macro(a=1) }}` | `<template :include="x" a={1} />` | Macros become component files |
| `{% call macro(a=1) %}body{% endcall %}` | `<template :include="x" a={1}>body</template>` | Default slot is implicit |
| `{# comment #}` | `{# comment #}` | Identical syntax |
| `{{ x \| length }}` | `{len(x)}` | Python builtin |
| `{{ x \| upper }}` | `{x.upper()}` | Python method |
| `{{ x \| default('-') }}` | `{x or '-'}` | Or `x if x else '-'` |
| `{{ x \| join(', ') }}` | `{', '.join(x)}` | Python method |
| `{{ x \| capitalize }}` | `{x.capitalize()}` | Python method |
| `{{ x \| date('Y-m-d') }}` | `{x.strftime('%Y-%m-%d')}` or push to presenter | Python's strftime |
| `{% if x is defined %}` | n/a — undeclared names are check-time errors | Different model |
| `{% if x is none %}` | `:if={x is None}` | Python comparison |
| `{% raw %}{x}{% endraw %}` | `{{x}}` for literal `{`, `}}` for literal `}` | f-string-style escape |

### Template inheritance

Jinja's `{% extends %}` + `{% block %}` pattern translates to **include with slots.** One mechanism (`:include` + named slots) covers both reuse cases instead of having `extends` and `include` as separate concepts.

**Before** (Jinja base):

```jinja
{# templates/layouts/base.html #}
<html>
  <head><title>{% block title %}Default{% endblock %}</title></head>
  <body>
    <nav>{% block nav %}{% endblock %}</nav>
    <main>{% block content %}{% endblock %}</main>
  </body>
</html>
```

```jinja
{# templates/pages/user_edit.html #}
{% extends "layouts/base.html" %}

{% block title %}Edit user{% endblock %}
{% block nav %}<a href="/users">← Users</a>{% endblock %}
{% block content %}
  <h1>Edit {{ user.name }}</h1>
  ...
{% endblock %}
```

**After** (Plain base):

```html
<!-- templates/layouts/base.plain -->
---
slots:
  title:
    default: "Default"
  nav: optional
  default: required
---
<html>
  <head><title>{title}</title></head>
  <body>
    <nav>{nav}</nav>
    <main>{children}</main>
  </body>
</html>
```

```html
<!-- templates/pages/user_edit.plain -->
---
attrs:
  user: app.presenters.UserPresenter
---
<template :include="layouts/base">
  <template slot="title">Edit user</template>
  <nav slot="nav"><a href="/users">← Users</a></nav>

  <h1>Edit {user.name}</h1>
  ...
</template>
```

Multi-level inheritance falls out naturally — `layouts/marketing.plain` includes `layouts/base.plain` with some slots filled, page templates include `layouts/marketing.plain` to override the remaining slots.

**What we lose**: `{{ super() }}` (accessing parent block's default content while overriding it) has no direct analog. The two workarounds:

- Most cases of `{{ super() }} - extra` can be expressed by passing the augmented value: `<template slot="title">Default - extra</template>` (just write the full string).
- For cases where the parent's content is genuinely dynamic, expose it via a *prop* on the layout rather than relying on slot defaults: `<template :include="layouts/base" title={f"{base_title} - extra"}>...`.

`{{ super() }}` is rare in practice; the workaround is small.

### Multi-branch conditionals (`if`/`elif`/`else`)

We have `:if={cond}` but no `:elif` / `:else`. For Jinja's:

```jinja
{% if user.is_admin %}<admin-panel />
{% elif user.is_paid %}<paid-panel />
{% else %}<free-panel />
{% endif %}
```

Two recommended patterns:

**Push the decision to the presenter** (the Plain-preferred answer):

```python
# UserPresenter
@property
def panel_path(self) -> str:
    if self.is_admin: return "panels/admin"
    if self.is_paid:  return "panels/paid"
    return "panels/free"
```

```html
<template :include={user.panel_path} />
```

The branch decision lives in tested Python; the template just renders the result.

**Disjoint conditions inline** (when there's no good presenter home):

```html
<admin-panel :if={user.is_admin} />
<paid-panel :if={user.is_paid and not user.is_admin} />
<free-panel :if={not user.is_admin and not user.is_paid} />
```

Verbose but explicit. The condition redundancy is a tell that the logic should probably be in a presenter.

### Iteration with empty fallback (`for/else`)

Jinja's `{% for x in xs %}{% else %}empty{% endfor %}` (the else branch runs when the iterable is empty):

```html
<ul :if={posts}>
  <li :for={post in posts}>{post.title}</li>
</ul>
<p :if={not posts}>No posts yet.</p>
```

Pythonic. No new directive needed.

### Loop variables (`loop.index`, `loop.first`, `loop.last`)

Jinja's `loop.*` magic variables don't exist in our model. Use Python's `enumerate`:

```html
<li :for={(i, post) in enumerate(posts)}>
  <span :if={i == 0}>FIRST</span>
  {post.title}
</li>
```

For `loop.last`, compare against `len(items) - 1`. For `loop.index`, use the unpacked index directly. For more elaborate cases (alternating styles, first-of-group), push to a presenter that pre-computes the metadata as part of the item.

### Local variables (`{% set x = ... %}`)

The Pythonic answer: **compute in the presenter.** The presenter property is named, testable, and reusable. The template just reads it.

For one-off in-template binding (rare), Python's walrus operator inside an expression works:

```html
<div>{(total := sum(p.price for p in cart)), f"${total:.2f} ({len(cart)} items)"}</div>
```

Awkward enough that the presenter approach almost always wins.

### Filters (`|filter`)

No filter pipeline. Use Python methods directly. The translation table above covers the common ones. For project-specific helpers, import them via the `imports:` frontmatter block and call them as functions:

```yaml
imports:
  - from app.helpers import format_date, currency, truncate
```

```html
<p>{format_date(post.created_at)}</p>
<p>Price: {currency(item.price)}</p>
<p>{truncate(post.body, 100)}</p>
```

### Custom Jinja globals

Jinja registers globals via `env.globals[name] = value` in setup code. In Plain templates, the equivalent is **explicit imports** in the using template's frontmatter. No global registration mechanism — each template declares what it actually uses.

This is slightly more verbose at the template level but dramatically more readable when debugging ("where does `format_date` come from?" — answer is at the top of the file).

### `{% autoescape %}`, `{% trans %}`, `{% spaceless %}`, `{% do %}`

| Jinja feature | Plain answer |
|---|---|
| `{% autoescape %}` | Not supported. One escape policy (contextual). Use `Markup()` from Python side for opt-out. |
| `{% trans %}` | Not in v1 spec. Will need an i18n story — likely a translation function imported via `imports:` and called as `{_("Hello")}`. |
| `{% spaceless %}` / `{%- -%}` | Handled by the formatter, not as inline syntax. The compiler emits compact HTML; the formatter normalizes source-level whitespace. |
| `{% do %}` | Not supported. Compute in the presenter. |
| `{% with %}` | Use a presenter or walrus. |

### Variable scoping

Jinja has complex scoping rules — variables defined inside `{% for %}` don't leak out by default, etc. Our model: Python scoping. Whatever Python's `for` / function-scope / comprehension semantics do is what templates do, because the compiled output is real Python.

## Reference points

This design is informed by but doesn't directly copy any single existing system. Lineage:

- **Phoenix HEEx**: HTML-aware compile-time validation, slots, declarative attrs, `:if`/`:for`-style directives. We borrow the architectural pattern (HTML-aware tokenizer + tag tree + AST compile) and the typed-attr philosophy. We don't use Elixir macros or the `~H` sigil shape; components are template files, not Elixir functions.
- **Web Components / `<template>` element**: `<template>` semantics (engine-processed inert content) and `slot="name"` attribute conventions. We don't use custom element tags or shadow DOM.
- **Go `html/template`**: contextual autoescape based on parse position. We adopt this directly.
- **Astro**: YAML/frontmatter file structure, dotted-type-path expressions, build-time validation. We don't adopt TypeScript-as-frontmatter — Python types in YAML, parsed via `ast.parse`.
- **Razor**: HTML-first with embedded language expressions, compiled to a typed render unit. Conceptual model.
- **Svelte**: `{python_expr}` (single-brace) interpolation. We don't adopt `{#if}/{/if}` block forms — element-directive-only.
- **Jinja**: `FileSystemLoader` resolution semantics with precedence. We don't adopt Jinja's tag syntax or template inheritance.

The design's distinctness vs all of these: no language to learn that isn't already HTML or Python; no component registry of any kind; no block forms; no filters; no decorators; no Python-side component classes. The smallest template engine that does what HTML genuinely requires and hands everything else back to Python.

## Open design questions

These remain unresolved and would be decided during prototyping:

1. **File extension**: `.plain`, `.html` (overrides Jinja's), `.phtml`, `.html.plain`, or something else. Probably `.plain` during migration, `.html` once Jinja is retired.
2. **Walrus operator support inside `{}`**: should `{(x := expensive()), x.foo}` be allowed for in-template local bindings? Lean yes (it's just Python), but worth confirming.
3. **Whether `{{ x }}` Jinja-style double-brace is supported as an alias** for `{x}`. Lean no — single source of truth on interpolation syntax.
4. **`:key={expr}` on `:for`**: for keyed iteration to enable morph-friendly DOM updates with paxi. Probably yes, but design depends on the hypermedia layer's needs.
5. **`<template :include={expr}>` for dynamic dispatch**: path is a Python expression resolving to a string. Useful for polymorphic rendering. Lean yes but defer to see if it's needed.
6. **Slot `yields:` declaration form**: the type of the value passed to `:as={var}` callers. Probably `yields: Type` in the slot's frontmatter declaration. Needs concrete syntax shape.
7. **Allowed-prefix validation on `dict[str, str]` attrs**: HEEx's `:global` validates allowed attr prefixes (e.g. only `aria-*`, `data-*`, `hx-*`). We need a Pythonic way to express this — possibly `Annotated[dict[str, str], AllowedPrefixes("data-", "aria-")]` — or just punt to runtime check and skip static enforcement of the prefix rule.
8. **Compiler IR shape**: should the compiled output preserve a static/dynamic split (HEEx-style) for future compile-time partial caching, even though v1 just emits a flat render function?

## Lessons explicitly absorbed from HEEx's experience

These are corrections HEEx had to make, or unresolved issues they're still living with, baked into our design upfront:

- **`{...}` interpolation only inside attribute values**, not `<%= %>` blocks. HEEx originally allowed both and had to disallow EEx-style attribute interpolation to enable HTML-aware escaping. We start with `{...}` only.
- **Typed components from day 1**. HEEx shipped without `attr`/`slot` declarations and added them in LiveView 0.18. We design with `attrs:`/`slots:` as the foundation.
- **`<script>`/`<style>` policy explicit upfront**. HEEx has accumulated issues around interpolation in these contexts. We declare "opaque, no interpolation" from the start.
- **HTML comment policy explicit**. HEEx issue #1590 still open. We declare "pass-through verbatim, no interpolation; use `{# ... #}` for template-only comments."
- **Slot-content binding uses Python's `as` keyword**, not the JS-flavored `:let`. Same semantic, native vocabulary.
- **Enum constraints via `Literal[...]`** rather than a separate `values:` field. Python's type system already does this.
- **Cache invalidation graph from day 1**. The compiled-output cache must invalidate on changes to the template, its frontmatter-resolved types, and any `:include`d template. Dependency-graph tracking goes in the compiler design, not bolted on later.
- **Tree-sitter grammar is a separate workstream from the runtime parser** (HEEx's approach). The CLI checker ships first; editor support comes later.

## Known gaps we share with HEEx

These are limitations that aren't worth solving in v1 but should be documented as known:

- **No semantic HTML tree validation**. `<p><div></div></p>` is structurally invalid HTML but parses fine. HEEx has this on their roadmap; we'd inherit it. Validation would require porting WHATWG content-model rules.
- **Type checking on `attr` literal-only is HEEx's behavior; we plan to do better**. Because we use pyright/ty over extracted expressions, *variable* values flowing into typed attrs get checked too — not just literals. This is a real upgrade vs HEEx's current state.
- **Inline behavior in third-party JS libraries** (Alpine `x-data="..."`, framework-specific attribute conventions): mostly fine because we treat unknown attributes as pass-through strings; expression parsing is opt-in via `{...}`. HEEx's tokenizer is stricter and fights some of these patterns more.
