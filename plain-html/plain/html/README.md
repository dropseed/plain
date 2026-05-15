# plain.html

**An HTML-aware template engine with components, contextual autoescape, and statically checkable expressions.**

- [Overview](#overview)
- [Templates](#templates)
- [Expressions](#expressions)
- [Blocks](#blocks)
    - [`{% if %}` / `{% elif %}` / `{% else %}`](#if--elif--else)
    - [`{% for %}`](#for)
    - [`{% slot %}`](#slot)
    - [`{# comment #}`](#comment)
    - [`{% raw %}`](#raw)
- [Components](#components)
- [Slots](#slots)
- [Frontmatter](#frontmatter)
- [Views](#views)
- [Security](#security)
- [CLI](#cli)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Templates are `.html` files under your app's `templates/` directory. Expressions are real Python wrapped in `{{ ... }}`. Components are just other templates — you import them by name and invoke them as PascalCase tags.

Here's a complete template at `app/templates/hello.html`:

```html
<p>Hello, {{ name }}!</p>
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

Control flow uses `{% %}` blocks that wrap the content they affect. Rendering a list of tasks looks like:

```html
<ul>
  {% for task in tasks %}
  <li>{{ task.title }}</li>
  {% endfor %}
</ul>
```

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

The same naming is used in the `components:` frontmatter key — absolute names look up across the configured `templates/` directories, and names beginning with `./` or `../` resolve relative to the calling template.

See [`find_template`](./loader.py#find_template) for the full resolution rules.

## Expressions

Anywhere you can write text, you can write `{{ python_expression }}`. The expression is real Python — function calls, attribute access, comparisons, comprehensions, anything that fits on one line:

```html
<h1>Hello, {{ user.name }}!</h1>
<p class="meta">{{ len(items) }} item{{ "s" if len(items) != 1 else "" }}</p>
```

Names in the expression resolve against the context you pass to `render(...)`. Bindings introduced by `{% for %}` (and the template's own frontmatter `attrs:`, `slots:`, and `imports:`) are also in scope.

Expressions work in attribute values too. Always quote attribute values — `attr="..."`.

When the value mixes literal text with `{{ }}`, each expression is interpolated into the string and escaped into the value:

```html
<a href="/users/{{ user.id }}/" class="btn {{ css_class }}">Profile</a>
```

When the value is **exactly one `{{ }}` expression**, the attribute takes the expression's actual typed result — not just its string form. This unlocks boolean and "omit me" semantics:

```html
<a href="{{ url('home') }}">Home</a>
<input required="{{ field.required }}">
```

- `True` renders the bare attribute (`required`); `False` or `None` omits it entirely.
- A list joins its truthy members with spaces — handy for class lists: `class="{{ ["btn", "btn-lg" if large else None] }}"`.
- Any other value is stringified and escaped for its position.

A single `{` or `}` is ordinary text — only the `{{ ... }}` pair starts an expression. CSS and JavaScript braces in a text body or attribute value are just literal characters, and a JSON literal in an attribute passes through untouched:

```html
<p>Use the syntax { key: value } in your config.</p>
<button hx-vals='{"id": 42}'>Save</button>
```

You can still mix a live expression into that literal text:

```html
<button hx-vals='{"id": {{ item.id }}}'>Save</button>
```

To emit a literal `{{`, `{%`, or `{#`, wrap the region in [`{% raw %}`](#raw).

## Blocks

Blocks are `{% ... %}` tags that wrap the content they affect. They control rendering rather than emitting HTML, and they read as a layer visibly separate from the surrounding markup.

The blocks are `{% if %}` / `{% elif %}` / `{% else %}`, `{% for %}`, `{% slot %}`, `{# comment #}`, and `{% raw %}`.

Blocks are **HTML-aware**: each block — and each branch of an `{% if %}` chain — must contain a balanced HTML fragment. An element opened inside a block must be closed inside the same block. A _tag straddle_ like this is a compile error:

```html
<!-- Compile error: <div> opened in one branch, closed outside it -->
{% if wide %}
<div class="wide">
  {% else %}
  <div class="narrow">{% endif %} {{ content }}</div>
</div>
```

Vary the whole element with two complete branches instead, or extract a component:

```html
{% if wide %}
<div class="wide">{{ content }}</div>
{% else %}
<div class="narrow">{{ content }}</div>
{% endif %}
```

Blocks also **cannot appear inside a start tag** — `<button {% if disabled %}disabled{% endif %}>` is a compile error. Conditional attributes are done with an expression value instead: `disabled="{{ is_disabled }}"` (a falsy value omits the attribute). This keeps every start tag a clean, parseable unit.

### `{% if %}` / `{% elif %}` / `{% else %}`

```html
{% if alert %}
<div class="alert">{{ alert.message }}</div>
{% endif %}
```

The wrapped content only renders when the expression is truthy. Chain conditions with `{% elif %}` and `{% else %}`:

```html
{% if status == "open" %}
<p>Open</p>
{% elif status == "pending" %}
<p>Pending</p>
{% else %}
<p>Closed</p>
{% endif %}
```

A `{% if %}` block can wrap any amount of content, with or without a surrounding element.

### `{% for %}`

```html
{% for task in tasks %}
<li><a href="/tasks/{{ task.id }}/">{{ task.title }}</a></li>
{% endfor %}
```

The wrapped content is repeated for each iteration. The clause is a Python comprehension clause — one `for` plus any number of `if` filters:

```html
{% for task in tasks if task.visible %}
<li>{{ task.title }}</li>
{% endfor %} {% for t in tasks if t.visible if not t.archived %}
<li>{{ t.title }}</li>
{% endfor %}
```

Tuple unpacking works, parenthesized or not: `{% for (i, item) in enumerate(items) %}`.

There is **no `{% empty %}` clause and no `for`-`else`**. Jinja overloads `else` on `for` to mean "the iterable was empty," which contradicts Python's `for/else` semantics — so plain.html doesn't have it. Render the empty case with a separate `{% if %}`:

```html
{% if notes %}
<ul>
  {% for note in notes %}
  <li>{{ note.title }}</li>
  {% endfor %}
</ul>
{% endif %} {% if not notes %}
<p>No notes yet.</p>
{% endif %}
```

Multiple `for` clauses in one tag (`{% for x in xs for y in ys %}`) are a compile error — nest a second `{% for %}` block instead.

### `{% slot %}`

`{% slot "name" %}...{% endslot %}` marks content, on the caller side, as content for a named slot of the component it sits inside:

```html
<Card>
  {% slot "header" %}
  <h2>Welcome</h2>
  {% endslot %}
  <p>Body content.</p>
</Card>
```

The slot name is a literal quoted string — slot names are static. A `{% slot %}` block can wrap one or more elements. Content not wrapped in a `{% slot %}` block falls through to the component's default slot. See [Slots](#slots) for the full picture.

### `{# comment #}`

A server-side comment. It is dropped from the rendered output entirely — unlike an HTML comment (`<!-- -->`), which ships to the browser.

```html
{# TODO: paginate this list once it grows #}
<ul>
  {% for note in notes %}
  <li>{{ note.title }}</li>
  {% endfor %}
</ul>
```

### `{% raw %}`

Everything between `{% raw %}` and `{% endraw %}` is emitted verbatim — no `{{ }}`, `{% %}`, or `{# #}` recognition inside. This is how you emit a literal delimiter:

```html
{% raw %}
<p>Write {{ name }} to interpolate a value.</p>
{% endraw %}
```

That renders the literal text `<p>Write {{ name }} to interpolate a value.</p>` — braces and all.

## Components

A component is just a template designed to be used from another template. There's no registry and no separate file type — write a regular `.html` file, declare its inputs in frontmatter, and import it.

To use a component, list it under the `components:` frontmatter key, then invoke it as a PascalCase tag:

```html
<!-- app/templates/components/Button.html -->
--- attrs: href: str label: str variant: str = "primary" ---
<a href="{{ href }}" class="btn btn-{{ variant }}">{{ label }}</a>
```

```html
<!-- caller -->
--- components: - components/Button ---
<button href="/signup" label="Sign up" />
<button href="/learn" label="Learn more" variant="ghost" />
```

Each `components:` entry is a template path. The tag name is the path's last segment — so `components/Button` becomes `<Button>`. Use `as Name` to rename:

```html
---
components:
  - components/Card
  - base as Base
---
```

`base.html` is now usable as `<Base>...</Base>`.

Rules:

- The resolved tag name **must be PascalCase** — that's how the engine tells a component apart from an HTML element. A lowercase tag is always plain HTML; you cannot shadow `<button>` with a component.
- Component tags can be self-closing: `<Card />`.
- Attributes you pass to a component tag become its `attrs:` values; child content becomes its slots.
- An unknown component tag (one not listed in `components:`) is a compile error.
- A name collision in `components:` is a compile error.

Layouts are ordinary components. There's no special `layout:` or `extends` mechanism — a page imports its layout (`base as Base`) and renders its content inside `<Base>...</Base>`, passing slot content in.

## Slots

A component declares which slots it accepts in its `slots:` frontmatter and reads them as bindings in its body. The default slot is `{{ children }}`; named slots are referenced by their declared name.

```html
<!-- app/templates/components/Card.html -->
--- slots: header: optional default: required ---
<section class="card">
  {% if header %}
  <header>{{ header }}</header>
  {% endif %} {{ children }}
</section>
```

When you invoke the component, unmarked direct children fall through to the **default slot**. Mark content for a **named slot** with a `{% slot "name" %}` block:

```html
---
components:
  - components/Card
---

<Card>
  {% slot "header" %}
  <h2>Welcome</h2>
  {% endslot %}
  <p>Body content.</p>
</Card>
```

A `{% slot %}` block can wrap multiple elements:

```html
<Card>
  {% slot "header" %}
  <h2>Welcome</h2>
  <p class="subtitle">Glad you're here.</p>
  {% endslot %}
  <p>Body content.</p>
</Card>
```

Each `slots:` entry uses the shorthand `name: required` or `name: optional`. A required slot arrives as `Markup`; an optional slot that the caller doesn't provide arrives as `None`. The `required` flag is also what makes `plain html check --typecheck` error when a caller forgets a required slot.

Two `{% slot %}` blocks with the same name is a compile error.

Slot values are rendered HTML. Inside a component they arrive as `Markup` — the `SafeString` type used throughout Plain for "already-escaped" content. `Markup(s)` and `mark_safe(s)` both wrap a string so the engine emits it verbatim; both names are auto-imported into every compiled template, and both are importable as `from plain.html import Markup, mark_safe` from Python.

## Frontmatter

A template can declare its inputs at the top of the file in YAML frontmatter, between `---` lines. Four keys are recognized:

```html
---
imports:
    - from datetime import date
    - from app.models import Project
components:
    - components/Card
    - base as Base
attrs:
    title: str
    project: Project
    updated: date = date.today()
slots:
    header: required
    default: required
---
<Base>
    {% slot "title" %}<header>{{ title }}</header>{% endslot %}
    <Card>
        {% slot "header" %}<header>{{ header }}</header>{% endslot %}
        <h1>{{ title }}</h1>
        <p>Updated {{ updated }} · {{ project.name }}</p>
        {{ children }}
    </Card>
</Base>
```

- **`imports:`** runs once at module load. Names you import here are available in every `{{ expr }}` in the file.
- **`components:`** lists the templates this file invokes as component tags. Each entry is a template path, optionally with `as Name` to rename. The resolved tag name must be PascalCase.
- **`attrs:`** declares the names you expect callers to pass — either via `render(context)` (top-level use) or as attributes on a component tag (component use). The short form is `name: type` or `name: type = default`. The expanded form is a mapping with `type:`, `default:`, `required:`, and `doc:` keys.
- **`slots:`** declares which slots the template renders. Each entry is `name: required` or `name: optional`.

Frontmatter is parsed via the `python-frontmatter` package (the same loader `plain.pages` uses). All four keys feed both the runtime defaults and the static type checker described in [CLI](#cli). See [`declarations.parse`](./typecheck/declarations.py#parse) for the validation rules.

## Views

`plain.html` ships a family of class-based views that render templates. They subclass `plain.views.View` and take care of the template lookup, context, and form-handling boilerplate.

```python
# app/views.py
from plain.html import TemplateView


class HomeView(TemplateView):
    template_name = "home.html"
```

```python
# app/urls.py
from plain.urls import Router, path
from . import views


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", views.HomeView, name="home"),
    ]
```

Other view classes for common patterns:

- [`FormView`](./views.py#FormView) — render a form on GET, validate and redirect on POST.
- [`DetailView`](./views.py#DetailView) — render a single object resolved by `get_object()`.
- [`ListView`](./views.py#ListView) — render a collection resolved by `get_objects()`.
- [`CreateView`](./views.py#CreateView) — `FormView` that calls `form.save()` on success.
- [`UpdateView`](./views.py#UpdateView) — `DetailView` + `FormView` for editing an existing object.
- [`DeleteView`](./views.py#DeleteView) — `DetailView` + `FormView` that deletes the object on POST.

`NotFoundView` is a catchall — it raises `NotFoundError404` before dispatch and renders `404.html`. Wire it as the last URL in a router to surface a styled 404 page. See [`NotFoundView`](./views.py#NotFoundView).

## Security

plain.html treats two things very differently.

**Template authors are trusted.** Frontmatter `imports:` runs at module load; `{{ python expressions }}` run at render time. These are application code, same trust level as `views.py`. plain.html does **not** sandbox templates. Do not render user-uploaded templates with this engine — there is no safe configuration that supports it.

**Data passed to templates is hostile by default.** Every `{{ expr }}` in text body or attribute value runs through the appropriate escape for its context. Authors opt out per-call with `mark_safe(value)` or `Markup(value)` — both produce a `SafeString` the engine emits verbatim, both are auto-imported in every compiled module, and both are deliberately greppable.

### Per-context escape table

| Position                                                                                      | Escape                          | Notes                                                                                                                                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Text body (`<p>{{ x }}</p>`)                                                                  | HTML entity escape              | `<` → `&lt;`, etc.                                                                                                                                                                                                                                                                     |
| Generic attribute (`<a class="{{ x }}">`)                                                     | HTML entity escape              | Same handler as text.                                                                                                                                                                                                                                                                  |
| URL attribute (`href`, `src`, `action`, `formaction`, `xlink:href`, `data`, `poster`, `cite`) | Scheme allow-list + HTML escape | Relative URLs pass through. An absolute URL whose scheme is outside `{http, https, mailto, tel, ftp, ftps}` resolves to the empty string.                                                                                                                                              |
| Event-handler attribute (`onclick=`, `on*=`)                                                  | **Compile error**               | HTML escape doesn't protect a JS context. Author must wrap the value in `mark_safe(...)` to opt in, or write a literal handler.                                                                                                                                                        |
| `<script>` body                                                                               | Opaque text                     | `{{ expr }}` syntax is **not** parsed inside script bodies — the content is emitted verbatim. To inject data into JS, set a `data-*` attribute (auto-escaped) and read it in JS, or use `Markup(json.dumps(value))` and put it in a separate `<script type="application/json">` block. |
| `<style>` body                                                                                | Opaque text                     | Same as `<script>`.                                                                                                                                                                                                                                                                    |

### What we do not protect against

- A template author writing `mark_safe(user_input)`. That call is the documented opt-out; auditing it is the author's responsibility.
- Bugs in the application's escape calls outside the template path.
- Open-redirect attacks: a `href="https://attacker.example.com/..."` is on the allow-list (it's a valid `https://` URL) and will render. Validating destination hosts is application logic.

### Implementation notes

- YAML frontmatter loading uses `python-frontmatter`'s safe loader — `!!python/object/apply` tags raise `ConstructorError` and do not execute.
- Render-time tracebacks point at the original `.html` source. The compiler remaps every generated AST node's line number back to the template line that produced it, and compiles with `co_filename = <template path>`, so an `AttributeError` from `{{ user.no_such_attr }}` shows up as `File "templates/x.html", line N` with the actual template line displayed by `linecache`.
- The on-disk compile cache lives at `<project>/.plain/html/` and is written with mode `0700`. Override the location with the `HTML_CACHE_DIR` setting, or disable the disk cache entirely with `HTML_CACHE_DISABLED = True` — both also accept Plain's standard `PLAIN_*` environment-variable overrides (`PLAIN_HTML_CACHE_DIR`, `PLAIN_HTML_CACHE_DISABLED`).

## CLI

Three commands under `plain html`:

```bash
plain html check        # parse + validate every template under app/templates/
plain html format       # canonicalize whitespace and attribute order in place
plain html compile      # pre-compile every template into the on-disk cache
```

- `plain html check --typecheck` also runs `{{ expr }}` content through your configured Python type checker (`ty` by default; `pyright` also supported). Each template's `attrs:`, `imports:`, and `components:` form the local scope, so component tags are checked at their call sites.
- `plain html format` is idempotent and conservative — it indents `{% %}` block bodies, while text content and whitespace inside inline parents, `<pre>`, `<textarea>`, `<script>`, and `<style>` are preserved byte-for-byte. Run `--check` to fail without writing.
- `plain html compile` is a deploy-time warm step: it pre-fills `<project>/.plain/html/` so the first render in production doesn't pay codegen cost.

All three accept paths or directories on the command line, or `-` to read source from stdin.

## FAQs

#### Why not Jinja2?

Jinja2 is excellent, and plain.html's `{% %}` block syntax is deliberately modeled on it. plain.html exists because a few specific problems are easier when the engine knows it's emitting HTML:

- **Contextual autoescape.** Jinja escapes every `{{ x }}` the same way. plain.html knows whether the expression sits in text, in a URL attribute, or in an event handler, and picks the right escape (or refuses dynamic data, in the event-handler case).
- **HTML-aware blocks.** `{% if %}` and `{% for %}` blocks must contain balanced HTML, so the engine guarantees well-formed output and catches tag straddles at compile time. An opaque text block can't do that.
- **Components as files.** A component is just another `.html` file, imported with the `components:` key and invoked as a tag. No `{% macro %}` blocks, no registry, no special import machinery.
- **Static checkability.** Because expressions are real Python and `attrs:` declares the local scope, `plain html check --typecheck` can run a Python type checker over every `{{ expr }}` in your templates — and over component call sites.

The `{% %}` block syntax is deliberately Jinja-shaped, so most Jinja constructs translate directly:

| Jinja                                 | plain.html                                                                                                          |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `{{ x }}`                             | `{{ x }}` — the expression is real Python                                                                           |
| `{{ x \| filter }}`                   | `{{ filter(x) }}` — filters are just Python calls                                                                   |
| `{% if x %}...{% endif %}`            | `{% if x %}...{% endif %}`                                                                                          |
| `{% if %}...{% elif %}...{% else %}`  | `{% if %}...{% elif %}...{% else %}...{% endif %}`                                                                  |
| `{% for x in xs %}...{% endfor %}`    | `{% for x in xs %}...{% endfor %}`                                                                                  |
| `{% for %}...{% else %}...`           | `{% for %}` (no `else`) plus a separate `{% if not xs %}` for the empty case                                        |
| `{% include "foo.html" %}`            | declare `foo` under `components:`, then invoke it as `<Foo />`                                                      |
| `{% block name %}...{% endblock %}`   | named slots — caller passes `{% slot "name" %}...{% endslot %}`                                                     |
| `{% macro x(...) %}...{% endmacro %}` | a component file (`components/X.html` with `attrs:`) invoked as `<X ... />`                                         |
| `{% extends "base.html" %}`           | no direct equivalent — invert the relationship: the page imports a layout component and passes slot content into it |
| `{% set x = ... %}`                   | no equivalent — compute the value in the view, or call Python inline in `{{ }}`                                     |
| `{%- -%}` whitespace trims            | no equivalent — whitespace is the formatter's job (`plain html format`)                                             |

#### How do I invoke a component?

List its template path under the `components:` frontmatter key, then write it as a PascalCase tag. `components/Card` becomes `<Card>`; use `as Name` to rename. Attributes on the tag become the component's `attrs:`, and child content becomes its slots. See [Components](#components).

#### Can I render user-uploaded templates?

No. See [Security](#security) — `imports:` runs at module load and `{{ ... }}` expressions execute real Python. There is no safe configuration for hostile authors.

#### Can I render Markdown or other non-HTML text?

Use `render_text_source(source, context)`. It interpolates a non-HTML body in text mode: only `{{ expr }}`, `{% raw %}…{% endraw %}`, and `{# #}` are recognized — everything else (including `<tags>`, autolinks, and other `{% … %}`) is literal text, and expressions are emitted unescaped. This is how `plain.pages` interpolates Markdown bodies: Markdown is not balanced HTML, so it can't go through the HTML-aware `render` / `render_source`. `{% if %}` / `{% for %}` blocks are HTML-mode only.

#### How do I write a literal `{`?

Just write it. A single `{` or `}` is ordinary text — only the `{{ ... }}` pair starts an expression. JSON literals like `{"id": 42}` pass through untouched. To emit a literal `{{`, `{%`, or `{#`, wrap the region in `{% raw %}...{% endraw %}` — see [`{% raw %}`](#raw).

#### How do I do a conditional attribute?

You can't put a `{% if %}` block inside a start tag. Use an expression value instead: `disabled="{{ is_disabled }}"`. A `True` value renders the bare attribute, a falsy value (`False`/`None`) omits it. See [Expressions](#expressions).

#### How do `components:` paths resolve?

The same way `Template(name)` does. Absolute names (`components/Card`) walk the configured `templates/` directories — the app's own `templates/` first, then each installed package's `templates/`. Relative names (`./Card`, `../layouts/Page`) resolve against the directory of the calling template. See [`find_template`](./loader.py#find_template).

#### How does this interact with `plain.htmx`?

plain.html emits plain HTML — `hx-*` attributes work as-is. HTMX's `hx-vals` attribute expects literal JSON, and single braces are literal text, so it just works:

```html
<button hx-post="/save" hx-vals='{"id": {{ item.id }}}'>Save</button>
```

Only the `{{ item.id }}` pair is a live expression; the surrounding braces render verbatim.

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
<p>Hello, {{ name }}!</p>
```

Render it:

```python
from plain.html import Template

Template("hello").render({"name": "Dave"})
```
