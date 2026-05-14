# plain.html

**An HTML-aware template engine with components, contextual autoescape, and statically checkable expressions.**

- [Overview](#overview)
- [Templates](#templates)
- [Expressions](#expressions)
- [Directives](#directives)
    - [`:if`](#if)
    - [`:for`](#for)
    - [`:include`](#include)
- [Slots](#slots)
- [Frontmatter](#frontmatter)
- [Components](#components)
- [Security](#security)
- [CLI](#cli)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Templates are `.html` files under your app's `templates/` directory. Expressions are real Python wrapped in `{ ... }`. Components are just templates you include from other templates.

Here's a complete template at `app/templates/hello.html`:

```html
<p>Hello, {name}!</p>
```

Render it from a view:

```python
from plain.html import Template

html = Template("hello").render({"name": "Dave"})
# '<p>Hello, Dave!</p>'
```

Or render a file path directly:

```python
from pathlib import Path
from plain.html import render

html = render(Path("app/templates/hello.html"), {"name": "Dave"})
```

`Template(name)` is the path-by-name wrapper used by `TemplateView`, the admin, and the toolbar. `render(path)` is the lower-level entry point — both go through the same compiler.

## Templates

Templates live under a `templates/` directory, either in your app or in an installed package. The loader walks `app/templates/` first, then each installed package's `templates/`.

```
app/
  templates/
    base.html
    layouts/
      page.html
    components/
      Card.html
```

You reference templates by name without the `.html` suffix:

```python
Template("layouts/page")
Template("components/Card")
```

Names that begin with `./` or `../` are relative to the calling template (used inside `:include`). Everything else is an absolute lookup across the configured `templates/` directories.

See [`find_template`](./loader.py#find_template) for the full resolution rules.

## Expressions

Anywhere you can write text, you can write `{python_expression}`. The expression is real Python — function calls, attribute access, comparisons, comprehensions, anything that fits on one line:

```html
<h1>Hello, {user.name}!</h1>
<p class="meta">{len(items)} item{"s" if len(items) != 1 else ""}</p>
```

Names in the expression resolve against the context you pass to `render(...)`. Bindings introduced by `:for` (and the template's own frontmatter `attrs:` / `imports:`) are also in scope.

Expressions work in attribute values too — quoted, unquoted, or mixed with text:

```html
<a href="/users/{user.id}/" class={css_class}>Profile</a>
```

To write a literal `{` or `}`, double it: `{{` and `}}`. That's the same f-string-style escape Jinja uses.

## Directives

Directives are special attributes prefixed with `:`. They control rendering rather than emitting HTML.

### `:if`

```html
<div :if={alert} class="alert">{alert.message}</div>
```

The element (and its children) only renders when the expression is truthy. Use `<template :if={...}>...</template>` for a conditional block with no surrounding element.

### `:for`

```html
<li :for={task in tasks}>
    <a href="/tasks/{task.id}/">{task.title}</a>
</li>
```

The element is repeated for each iteration. Tuple unpacking works: `:for={(i, item) in enumerate(items)}`.

### `:include`

```html
<template :include="components/Card" title="Hello" />
```

Includes another template at this position. The literal-string form (`:include="..."`) is resolved at compile time, so the included template is compiled alongside the parent and pulled directly into its module. The expression form (`:include={component_name}`) resolves at render time:

```html
<template :include={card_or_panel} title="Hello" />
```

Absolute paths walk the configured `templates/` directories. Relative paths (`./Card`, `../layouts/Page`) resolve against the calling template. See [`find_template`](./loader.py#find_template).

## Slots

When you include a component, the body of the `<template :include="...">` tag becomes its **default slot** (also reachable as `children`). The component renders it wherever it references `{children}`:

```html
<!-- app/templates/components/Card.html -->
---
slots:
    default: Markup
---
<section class="card">{children}</section>
```

```html
<!-- caller -->
<template :include="components/Card">
    <p>Hi there.</p>
</template>
```

Add named slots by giving children a `slot="..."` attribute. The component references each by name:

```html
<!-- app/templates/components/Card.html -->
---
slots:
    header: Markup
    default: Markup
---
<section class="card">
    <header>{header}</header>
    {children}
</section>
```

```html
<template :include="components/Card">
    <template slot="header"><h2>Welcome</h2></template>
    <p>Body content.</p>
</template>
```

Children without a `slot=` attribute fall through to the default slot.

## Frontmatter

A template can declare its inputs at the top of the file in YAML frontmatter, between `---` lines. Three keys are recognized:

```html
---
imports:
    - from datetime import date
    - from app.models import Project
attrs:
    title: str
    project: Project
    updated: date = date.today()
slots:
    header: Markup
    default: Markup
---
<section>
    <header>{header}</header>
    <h1>{title}</h1>
    <p>Updated {updated} · {project.name}</p>
    {children}
</section>
```

- **`imports:`** runs once at module load. Names you import here are available in every `{expr}` in the file.
- **`attrs:`** declares the names you expect callers to pass — either via `render(context)` (top-level use) or as attributes on a `:include` site (component use). The short form is `name: type` or `name: type = default`. The expanded form is a mapping with `type:`, `default:`, `required:`, and `doc:` keys.
- **`slots:`** declares which named slots the template renders. Each entry is `name: required` or `name: optional`, or an expanded mapping with `required:` and `yields:` keys.

Frontmatter is parsed via the `python-frontmatter` package (the same loader `plain.pages` uses). All three keys feed both the runtime defaults and the static type checker described in [CLI](#cli). See [`declarations.parse`](./typecheck/declarations.py#parse) for the validation rules.

## Components

A component is just a template designed to be included. There's no registry and no separate file type — write a regular `.html` file, declare its inputs in frontmatter, and `:include` it.

```html
<!-- app/templates/components/Button.html -->
---
attrs:
    href: str
    label: str
    variant: str = "primary"
---
<a href={href} class="btn btn-{variant}">{label}</a>
```

```html
<template :include="components/Button" href="/signup" label="Sign up" />
<template :include="components/Button" href="/learn" label="Learn more" variant="ghost" />
```

A common convention is to capitalize component file names (`Card.html`, `Button.html`) so they read like component tags in the caller — but the engine doesn't care.

## Security

plain.html treats two things very differently.

**Template authors are trusted.** Frontmatter `imports:` runs at module load; `{python expressions}` run at render time. These are application code, same trust level as `views.py`. plain.html does **not** sandbox templates. Do not render user-uploaded templates with this engine — there is no safe configuration that supports it.

**Data passed to templates is hostile by default.** Every `{expr}` in text body or attribute value runs through the appropriate escape for its context. Authors opt out per-call with `mark_safe(value)` or `Markup(value)` (the same callable, both auto-imported in every compiled module) — these calls are deliberately greppable.

### Per-context escape table

| Position                                                                                      | Escape                          | Notes                                                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Text body (`<p>{x}</p>`)                                                                      | HTML entity escape              | `<` → `&lt;`, etc.                                                                                                                                                                                                                                                                 |
| Generic attribute (`<a class={x}>`)                                                           | HTML entity escape              | Same handler as text.                                                                                                                                                                                                                                                              |
| URL attribute (`href`, `src`, `action`, `formaction`, `xlink:href`, `data`, `poster`, `cite`) | Scheme allow-list + HTML escape | Schemes outside `{http, https, mailto, tel, ftp, ftps}` cause the whole attribute to be omitted.                                                                                                                                                                                   |
| Event-handler attribute (`onclick=`, `on*=`)                                                  | **Compile error**               | HTML escape doesn't protect a JS context. Author must wrap the value in `mark_safe(...)` to opt in, or write a literal handler.                                                                                                                                                    |
| `<script>` body                                                                               | Opaque text                     | `{expr}` syntax is **not** parsed inside script bodies — the content is emitted verbatim. To inject data into JS, set a `data-*` attribute (auto-escaped) and read it in JS, or use `Markup(json.dumps(value))` and put it in a separate `<script type="application/json">` block. |
| `<style>` body                                                                                | Opaque text                     | Same as `<script>`.                                                                                                                                                                                                                                                                |

### What we do not protect against

- A template author writing `mark_safe(user_input)`. That call is the documented opt-out; auditing it is the author's responsibility.
- Bugs in the application's escape calls outside the template path.
- Open-redirect attacks: a `href="https://attacker.example.com/..."` is on the allow-list (it's a valid `https://` URL) and will render. Validating destination hosts is application logic.

### Implementation notes

- YAML frontmatter loading uses `python-frontmatter`'s safe loader — `!!python/object/apply` tags raise `ConstructorError` and do not execute.
- The compiler's emitted Python sets `__template_source__` on each module so tracebacks point at the original `.html` source.
- The on-disk compile cache lives at `<project>/.plain/html/` and is written with mode `0700`. Override the location with `PLAIN_HTML_CACHE_DIR`, or disable the disk cache entirely with `PLAIN_HTML_CACHE_DISABLED=1`.

## CLI

Three commands under `plain html`:

```bash
plain html check        # parse + validate every template under app/templates/
plain html format       # canonicalize whitespace and attribute order in place
plain html compile      # pre-compile every template into the on-disk cache
```

- `plain html check --typecheck` also runs `{expr}` content through your configured Python type checker (`ty` by default; `pyright` also supported). Each template's `attrs:` and `imports:` form the local scope.
- `plain html format` is idempotent and conservative — text content and whitespace inside inline parents, `<pre>`, `<textarea>`, `<script>`, and `<style>` are preserved byte-for-byte. Run `--check` to fail without writing.
- `plain html compile` is a deploy-time warm step: it pre-fills `<project>/.plain/html/` so the first render in production doesn't pay codegen cost.

All three accept paths or directories on the command line, or `-` to read source from stdin.

## FAQs

#### Why not Jinja2?

Jinja2 is excellent — Plain still ships it as the default engine. plain.html exists because a few specific problems are easier when the engine knows it's emitting HTML:

- **Contextual autoescape.** Jinja escapes every `{{ x }}` the same way. plain.html knows whether the expression sits in text, in a URL attribute, or in an event handler, and picks the right escape (or refuses dynamic data, in the event-handler case).
- **Components as files.** A `:include` is just another `.html` file. No `{% macro %}` blocks, no registry, no special import.
- **Static checkability.** Because expressions are real Python and `attrs:` declares the local scope, `plain html check --typecheck` can run a Python type checker over every `{expr}` in your templates.

#### Can I render user-uploaded templates?

No. See [Security](#security) — `imports:` runs at module load and `{...}` expressions execute real Python. There is no safe configuration for hostile authors.

#### How do I escape a literal `{`?

Double it: `{{` renders as `{`, `}}` renders as `}`. The same escape works in attribute values.

#### How does `:include` resolve paths?

Absolute names (`components/Card`) walk the configured `templates/` directories — the app's own `templates/` first, then each installed package's `templates/`. Relative names (`./Card`, `../layouts/Page`) resolve against the directory of the calling template. See [`find_template`](./loader.py#find_template).

#### How does this interact with `plain.htmx`?

plain.html emits plain HTML — `hx-*` attributes work as-is. The one thing to know: HTMX's `hx-vals` attribute expects literal JSON, so use the `{{` / `}}` escape pattern when you want a literal `{`:

```html
<button hx-post="/save" hx-vals='{{"id": {item.id}}}'>Save</button>
```

The double `{{`/`}}` becomes single `{`/`}` at render time, leaving the inner `{item.id}` as the only live expression.

## Installation

Install the `plain.html` package from [PyPI](https://pypi.org/project/plain.html/):

```bash
uv add plain.html
```

Add it to your installed packages:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.html",
]
```

Create your first template at `app/templates/hello.html`:

```html
<p>Hello, {name}!</p>
```

Render it:

```python
from plain.html import Template

Template("hello").render({"name": "Dave"})
```
