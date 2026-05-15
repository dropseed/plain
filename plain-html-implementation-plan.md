# `plain.html` — implementation plan

A phased plan for building `plain.html` (the new template engine specified in [plain-template-language](plain-template-language.md)) and migrating the Plain monorepo to it. Designed to be executable by an agent, one stage at a time, with explicit gates between stages.

## Goal

Ship a Plain-native HTML template engine that replaces Jinja for all templates currently in the repository, with no remaining Jinja dependency at completion.

## Scope

- In scope: `plain.html` package (new), template engine + compiler + static checker, full migration of `example/`, `plain.admin`, and any other in-repo packages with templates, removal of the old Jinja-based engine.
- Out of scope: External user code, third-party packages outside this monorepo, formal release notes, deprecation messaging beyond what the upgrade skill needs.

## Strategy

1. Build `plain.html` as a new package shipping alongside the existing Jinja-based engine.
2. New format lives in `html/` directories next to existing `templates/` directories.
3. An environment variable `PLAIN_HTML_RENDERER=new` (default off) flips the template loader to prefer `html/` over `templates/`, falling back to Jinja for templates not yet ported.
4. Each in-repo template is ported as its own changeset, exercised under both renderers via an **automated parity harness** (stood up in Phase 7, not at the end).
5. No cross-engine includes — a `.plain` template cannot `:include` a Jinja template, and a Jinja template cannot include a `.plain` template. Migration happens in **coherent inheritance chunks: layouts ported first, then their descendants in dependency order**.
6. When all in-repo templates are ported and parity-verified, remove `templates/` directories, drop the Jinja dependency, retire the env var, make the new engine the only engine.

## Verification approach

Verification is **automated**, not manual diff-review. The parity harness (built in Phase 7) drives a fixture list of `(route, user_id)` tuples and asserts equivalence between renderers:

1. Captures `uv run plain request /path` output under `PLAIN_HTML_RENDERER=` (Jinja).
2. Captures `uv run plain request /path` output under `PLAIN_HTML_RENDERER=new`.
3. Normalizes inter-tag whitespace and asserts equivalence.
4. Intentional differences (e.g., attribute order normalization, escape upgrades) are added to a per-route allowlist with a one-line rationale, so future regressions still fail.

The harness lives in the repo (e.g. `tests/parity/`) and runs under `./scripts/test`. Each migration phase grows the fixture list; the harness stays green throughout. Retired or repurposed in Phase 16.

## Upfront decisions (resolve before Phase 1)

These were left implicit in v1 of the plan. Pinning them now avoids mid-stream drift:

| Decision                               | Resolution                                                                                                                                                                                                                                                                                                                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CLI name**                           | `plain html check` during migration (matches the new package name). The spec writes `plain template check` for the post-Jinja future; rename in Phase 16 if `plain.templates` is rescoped.                                                                                                                                                                                                              |
| **File extension**                     | `.plain` for the full migration. Possible rename to `.html` post-Phase-16, treated as a separate decision.                                                                                                                                                                                                                                                                                              |
| **Compiled cache location**            | Dedicated `.plain-html-cache/` at project root, gitignored. Do **not** use `__pycache__/` — collides with Python's own bytecode cache management and isn't always writable.                                                                                                                                                                                                                             |
| **`Markup` type**                      | Reuse the existing `plain.utils.safestring.SafeString` / `mark_safe`. Re-export as `plain.html.Markup` for spec-aligned naming. No new type.                                                                                                                                                                                                                                                            |
| **`plain.templates` fate in Phase 16** | Becomes a thin shim that re-exports `plain.html`. Preserves import paths for any user code that touched the package; no separate retirement story.                                                                                                                                                                                                                                                      |
| **Presenters**                         | Documented convention, not a framework primitive. Plain pattern: a callable or dataclass in `app/presenters.py` (or `app/<feature>/presenters.py`) that returns the data shape the template's `attrs:` expects. Views construct presenters; templates only read attributes. No registration, no base class, no discovery — just Python. Document in `plain.html` README and link from migration phases. |
| **Migration env var**                  | `PLAIN_HTML_RENDERER=new`. Read once at loader init. Removed in Phase 16.                                                                                                                                                                                                                                                                                                                               |
| **Dual-engine cost during migration**  | Both Jinja and `plain.html` are runtime dependencies of `plain` between Phase 7 and Phase 16. Acceptable; Jinja drops from `pyproject.toml` only at Phase 16.                                                                                                                                                                                                                                           |

## Formatter & linter — decisions (resolve before Phase 9.5)

`plain html format` ships before migration begins in earnest (Phase 10) so each ported template can be formatted as it lands. These decisions are scoped to that work; they are not yet resolved.

**Prior art to study before writing code:**

- **Astro's prettier plugin** (`prettier-plugin-astro`) — `.astro` files are frontmatter (`---`) + HTML + `{js}`. Same architecture as ours. The issue tracker is where the lessons live.
- **djLint** — Python, template-aware (Django/Jinja/Nunjucks/Handlebars/Twig). Closest functional analog; long history of whitespace bugs to learn from.
- **Prettier's HTML core** (`prettier/src/language-html/`) — reference implementation of whitespace-sensitivity. Specifically `clean.js`, `print/element.js`, `utils/is-whitespace-sensitive-node.js`.
- **Prettier's test suite** (`prettier/tests/format/html/`) — the golden-file corpus that pins formatter output for every tricky shape. Worth studying both for what shapes they cover (whitespace edges, embedded scripts, void elements, nested inline/block) and for the snapshot infrastructure pattern. Strong reference for the corpus-test strategy below.
- **Svelte formatter** — different syntax, same class of problem (frontmatter-ish + HTML + embedded expressions).
- **Wadler, "A Prettier Printer"** (1998) — the doc-tree algorithm. ~12 pages; everyone descends from this.
- **WHATWG content categories** (https://html.spec.whatwg.org/multipage/dom.html#content-categories) — normative source for phrasing-content (inline) vs flow-content (block) and content-model rules. Tier-2 lint rules are tables transcribed from here.
- **prettier-plugin-tailwindcss** — reference if/when class sorting ships. Idempotency under `tailwind.config.js` resolution is non-trivial.

**Hard invariants the formatter must hold (table-stakes, not negotiable):**

1. **Idempotency**: `format(format(x)) == format(x)` for every input.
2. **Render equivalence**: `render(format(x), ctx) == render(x, ctx)` for every input and every context.

These two constrain every other decision below. Both gate the phase.

| Decision                          | Lean / status                                                                                                                                                                                                                   |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Whitespace sensitivity policy** | Cite WHATWG phrasing-content as the inline list; `<pre>`/`<textarea>`/`<script>`/`<style>` are verbatim; everything else is block. Document any departures in the README.                                                       |
| **Expression interior handling**  | Formatter does **not** modify bytes inside `{...}`. Treat as opaque in v1. Python style is ruff's job elsewhere.                                                                                                                |
| **Template comment preservation** | `{# … #}` is currently dropped at tokenize. **Blocker.** Phase 3 amended to emit a `TemplateCommentToken`/`Node` so the formatter can round-trip.                                                                               |
| **Attribute order**               | Preserve author order. Match Prettier.                                                                                                                                                                                          |
| **Attribute quoting**             | Normalize to double quotes; convert single only when no embedded `"` would force re-escaping.                                                                                                                                   |
| **Boolean attribute form**        | Normalize `disabled="disabled"` → `disabled`; leave `disabled` alone.                                                                                                                                                           |
| **Class attribute sorting**       | **Out of v1.** Idempotency under arbitrary CSS frameworks is non-trivial; revisit as an opt-in rule once Tailwind v4 integration story is locked.                                                                               |
| **Directive layout**              | `:if`/`:for`/`:include` formatted as ordinary attributes; same wrapping rules apply when a tag exceeds print width.                                                                                                             |
| **Frontmatter**                   | Preserved byte-for-byte in v1. Formatter never touches the YAML block.                                                                                                                                                          |
| **Print width / indent**          | 88 columns, 4-space indent. Matches ruff and Python convention; consistent with Plain's existing tooling.                                                                                                                       |
| **CLI surface**                   | `plain html format` (write) and `plain html format --check` (CI). Wired into `./scripts/fix` and `./scripts/check`. Not folded into `plain code` — kept distinct so the HTML formatter can be invoked standalone.               |
| **Lint rule taxonomy**            | Ruff-style codes: `PH001`…`PH0xx` for syntax/structure (Phase 8), `PH1xx` for content-model (Phase 17 tier 2), `PH2xx` for a11y (Phase 17 tier 3). Configured under `[tool.plain.html]` in `pyproject.toml`, per-rule severity. |
| **Performance budget**            | Format the entire monorepo's `.plain` corpus in under 2 seconds; format a single template in under 10 ms (warm). Set the budget now so we don't ship something glacial like early djLint.                                       |
| **Editor integration**            | CLI-only.                                                                                                                                                                                                                       |

### Conformance test strategy

The two hard invariants above can't be exhaustively tested with hand-written cases. Layered conformance tests catch regressions automatically and document the corner cases the formatter has learned. Wire these up in roughly this order:

1. **Repo corpus property test** (cheapest, highest signal). Walks every `.html` template in the repo, asserts: parses cleanly, `format(format(x)) == format(x)`, `render(format(x), ctx) == render(x, ctx)` with `>\s+<` normalization for flow-content whitespace. Real templates are the hardest corpus — no fixture maintenance, regressions surface the moment a template lands. Runs under `./scripts/test`.
2. **html5lib DOM comparison** (pure-Python, small dep). Parse source and formatted output with `html5lib`, compare normalized parse trees. Catches structural divergence even when text rendering happens to match. Stronger than the regex normalizer for tricky inline/block boundaries.
3. **Golden-snapshot corpus** (prettier-style). A fixture directory of `(input.html, expected.html)` pairs covering shapes the corpus doesn't naturally exercise — long attribute lists, deeply nested inline-in-block, `<pre>` with `{expr}`, comment-heavy templates, frontmatter edges. Each pair locks behavior; updates are explicit diffs in PRs. Mirrors Prettier's `tests/format/html/` layout. Grow incrementally as bugs surface.
4. **Optional: Nu Html Checker (vnu.jar)** as a CI-only validator step. The W3C reference HTML5 validator. Authoritative "did we break HTML semantics" signal. Heavy (Java dep); skip locally, run on CI.

Strategy: ship (1) with the formatter; add (2) when render-equivalence false positives start showing up; build out (3) as a regression net once the formatter stabilizes; (4) is opt-in if we hit a class of bugs DOM comparison misses.

## Open spec questions, mapped to phases

The [spec](plain-template-language.md) lists open design questions; each gets pinned to the phase where it gets decided:

| Spec open question                             | Decided in                                                                                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Walrus support inside `{}`                     | Phase 5 (compiler). Lean yes (it's just Python; falls out for free).                                                                           |
| `{{ x }}` double-brace alias                   | Phase 3 (tokenizer). Lean no — single interpolation syntax.                                                                                    |
| `:key={expr}` on `:for`                        | Deferred until hypermedia layer needs it. Not in v1 scope.                                                                                     |
| `<template :include={expr}>` dynamic dispatch  | Phase 4 + Phase 5. Lean yes (path-as-expression desugars cleanly).                                                                             |
| Slot `yields:` declaration form                | Phase 2 (frontmatter) + Phase 4 (tree builder) + Phase 9 (type check). Use spec's proposed shape: `yields: Type` under the slot's frontmatter. |
| `dict[str, str]` allowed-prefix validation     | Phase 9. Punt to runtime check for v1; revisit when `Annotated[]` story is cleaner.                                                            |
| Compiler IR static/dynamic split               | Defer. Phase 5 emits a flat render function. Phase 17+ may revisit.                                                                            |
| File extension long-term (`.plain` vs `.html`) | Decided post-Phase-16. Not part of migration.                                                                                                  |

## Phased sequence

Each phase has: deliverables, success criteria, agent verification steps. Phases run sequentially — finish a phase fully before starting the next. Phase 0 has no prerequisites; every later phase depends on the previous one.

---

### Phase 0 — Tracer bullet

**Goal**: validate the spec end-to-end on the hardest realistic template _before_ building broad infrastructure.

Deliverables:

- Pick one htmx-heaviest template in `plain.admin` (likely a data-browser fragment: row with inline-edit, OOB swap, or multi-target update). The fragment should exercise: slots, `:if`, `:for`, attribute splat, scoped slot binding (`:as`), URL-attribute escaping, htmx attribute pass-through.
- Build a throwaway prototype that walks the _entire_ pipeline for this one template: frontmatter parse → tokenize → tag tree → compile → render → produce HTML identical to the existing Jinja output.
- Capture any spec ambiguities, surface them to the user, and either get the spec updated or document the chosen interpretation as a decision.

Success criteria:

- The chosen template renders identically (modulo documented whitespace) under the prototype and Jinja.
- A short notes file at `scratch/tracer-notes.md` records: spec ambiguities found, decisions made, refinements needed to the formal phase sequence.

Verification:

```bash
# Whatever the chosen fragment's route is:
uv run plain request /admin/.../<fragment>  > /tmp/jinja.html
# Run the prototype's render() against the same inputs, capture output.
diff /tmp/jinja.html /tmp/prototype.html
```

The prototype is discarded after Phase 0; lessons inform Phases 1–7. Do not skip — this is the cheapest place to discover a fundamental design problem.

**Status: shipped; ready for public release.** Jinja is gone — `plain-templates` was deleted, every package has a `<pkg>/templates/` directory, the extension is `.html`, and `TemplateView`/`FormView`/`DetailView`/`ListView`/`UpdateView`/`DeleteView` live in `plain.html.views`. 119 templates across `plain`, `plain-admin`, `plain-observer`, `plain-toolbar`, `plain-flags`, `plain-jobs`, `plain-pages`, `plain-pageviews`, `plain-sessions`, `plain-email`, `plain-tailwind`, `plain-htmx`, `plain-loginlink`, `plain-oauth`, `plain-passwords`, `plain-redirection`, `plain-support`, and `example` — `plain html check --typecheck` is green across the lot. Smoke routes — `/`, `/tasks/`, `/admin/`, `/admin/ui`, `/observer/` — render end-to-end through plain.html.

Engine work: Phases 0–6 are landed (frontmatter, tokenizer, parser, AOT compiler with static + dynamic includes, slot composition, disk cache, security hardening, contextual escape via `_runtime.py`'s `escape_html` / `escape_attr` / `escape_url` with scheme allow-list, `on*=` compile error). The tree-walking interpreter is deleted; `engine.py` is a thin entry that delegates to `compiler.get_or_compile`. Phase 8 (`plain html check`) and Phase 9 (`--typecheck` via ty, with result caching and a pyright backend) are shipped and gate pre-commit. Phase 9.5 (`plain html format`) is shipped with corpus + DOM-comparison + snapshot + performance + frontmatter + render-DOM conformance tests.

Public-release prep (May 2026): typed settings registered in `default_settings.py` (`HTML_CACHE_DIR`, `HTML_CACHE_DISABLED`) with auto-bound `PLAIN_*` env-var overrides; `TemplateView` family and `TokenizeError` / `ParseError` / `CompileError` re-exported from `plain.html`; agent rule shipped at `plain-html/plain/html/agents/.claude/rules/plain-html.md`; `plain html compile` no longer crashes on bad frontmatter; tests reorganized (interpreter behavior tests moved to `internal/`, public contract tests added at `tests/public/test_template.py`, format render-equivalence promoted to `public/`, perf-gate added at `internal/test_compiler_perf.py`); parity harness deleted (migration done, interpreter deleted); 713 tests passing; `plain-html` wired into `scripts/test`. README documents views, has a Jinja translation table, and accurately describes the `Markup` / `mark_safe` relationship.

**What's open:**

- **Phase 17** (tier-2/tier-3 lint, class sorting, expression-interior formatting) — deferred as planned.

---

### Phase 1 — Package skeleton

Deliverables:

- New `plain.html/` package at the repo root, following the layout of other Plain packages (pyproject.toml, plain/html/ module dir, tests/, README.md).
- Added to the workspace.
- Initial README describing the new template format in 1-2 paragraphs, linking to the spec.
- Empty `plain.html.cli` placeholder for `plain html check` (not yet implemented).
- `plain.html.Markup` re-exports `plain.utils.safestring.SafeString` / `mark_safe` per the upfront decision.
- `plain.html` registered with `plain.runtime`; listed under INSTALLED_PACKAGES candidates for the migration.

Success criteria:

- `uv sync` includes plain.html.
- `uv run plain --help` lists `plain html` as a command group.
- Existing tests still pass.

Verification:

```bash
uv sync
uv run plain html --help
./scripts/test
```

---

### Phase 2 — Frontmatter parser

Deliverables:

- `plain.html.frontmatter` module that parses a `.plain` file into `(frontmatter_dict, template_body_string, source_map)`.
- YAML parsing for `attrs:`, `imports:`, `slots:` sections.
- `attrs:` accepts both inline (`name: type`) and expanded (`name: { type, required, doc }`) forms per the spec.
- Type-expression parser for attr `type:` values — calls `ast.parse(..., mode='eval')` on each string, validates it's a valid expression. Resolution of dotted names is deferred to Phase 9 (typecheck).
- `imports:` entries parsed and validated as real Python import statements via `ast.parse(..., mode='exec')`. Each import becomes an `ast.ImportFrom` / `ast.Import` node stored for later code-emission and typecheck.
- `slots:` entries support `required | optional` shorthand and the expanded form `name: { required, default, yields }`.
- `ParseError` exception with file/line/column.

Success criteria:

- Given a `.plain` file with frontmatter and body, returns the parsed structure with accurate source positions.
- Bad YAML, missing `---` fences, malformed type expressions, or malformed `imports:` statements raise `ParseError`.
- Unit tests in `plain.html/tests/internal/test_frontmatter.py`.

Verification:

```bash
./scripts/test plain.html
```

---

### Phase 3 — HTML-aware tokenizer

Deliverables:

- `plain.html.tokenizer` module that converts a template body string into a stream of tokens: tags (open/close/void/self-closing), attributes, text, expression spans (`{...}`), template comments (`{# #}`), HTML comments (`<!-- -->`).
- Template comments are emitted as a typed `TemplateCommentToken` (not dropped). Required so Phase 9.5's formatter can round-trip them; renderer discards them at render time.
- Strict mode — fails on unbalanced angle brackets, unterminated strings, etc.
- Each token carries `(start_line, start_col, end_line, end_col)`.
- `<script>` and `<style>` bodies tokenized as opaque text (no expression recognition); a `{...}` inside raises a `TokenizeError` per spec.
- `<template>` recognized as engine-aware; directives (`:if`, `:for`, `:as`, `:include`) recognized by name during tokenization with `{...}` or literal-string values.
- `slot="name"` attribute on any element recognized for slot routing.
- Decision: only single-brace `{...}` interpolation; `{{...}}` is the f-string-style escape for a literal `{` per spec.

Success criteria:

- Well-formed templates tokenize cleanly with accurate positions.
- Malformed templates raise `TokenizeError` with line/column.
- Unit tests covering: simple tags, void elements, attribute splat, expression spans in text and attributes, script/style opacity (and refusal), comments, directive attributes, slot attribute.

---

### Phase 4 — Tag tree builder

Deliverables:

- `plain.html.parser` module that converts a token stream into a tag tree.
- Balance validation: every open tag has a matching close (or is self-closing/void).
- Void elements (`<img>`, `<br>`, etc.) cannot have children.
- `<template :include>`, `<template :if>`, `<template :for>`, `<template slot="...">`, `<template>` (fragment) all recognized as distinct constructs.
- Directives `:if`/`:for`/`:as`/`:include` on a tag attach as structured metadata, not flat attributes.
- `:include` is restricted to `<template>` only; using it elsewhere raises a parse error per spec.
- Scoped-slot wiring: `<template slot="name" :as={var}>` parses both the slot routing and the binding.
- `yields:` in slot frontmatter is preserved on the tree's slot metadata for Phase 9.
- Decision: support `<template :include={expr}>` (dynamic path expression) per spec open question — the path attribute is either a literal string or a `{...}` expression node.

Success criteria:

- Balanced trees parse; unbalanced trees fail with helpful errors.
- Void-element-with-children fails.
- `:include` on non-`<template>` fails.
- Tree contains structured directive info, not just raw attributes.
- Unit tests for each construct.

---

### Phase 5 — Compile to Python render function

The interpreter (`engine.py`) gets the semantics right but is 6–14× slower than Jinja on realistic templates (see `plain-html/bench/render.py`). The walk and the per-`{expr}` `eval(code, scope)` dominate. AOT codegen replaces both with real Python: no walk, expressions inlined as Python sub-expressions, locals instead of dict lookups. That's the only path to Jinja-class steady-state per-call cost — caches alone can't close the gap.

#### Goals

- **Per-render cost ≤ 2× Jinja** on the existing bench cases (`tiny`, `medium_list`, `expression_heavy`, `nested_loops`, `conditionals`). Stretch: ≤ 1.5×.
- **Byte-equivalent output** to the interpreter for every template in the repo across a fixed context fixture (corpus parity test, runs in CI).
- **Debuggable**: tracebacks point to the original `template.html:line:col`, not to a hash-named cache file.
- **Transparent**: `render_source(...)` / `render(...)` keep their current signatures. Migration is a runtime switch, not an API change.

#### Non-goals

- Sandboxing / restricted execution. Frontmatter `imports:` already runs arbitrary Python; templates are trusted code. Compiled output gets the same trust.
- Deferred / lazy slots. Slots render eagerly to `Markup` strings exactly like the interpreter; rich callable slots can come later if a real use case shows up.
- Statically resolving every name. Names not declared in `attrs:` / `imports:` fall through to a runtime context lookup — same behavior as today.

#### Output shape

Each `.html` file compiles to one Python module. Concrete example for `html/components/card.html`:

```html
---
attrs:
    title: str
    href: str | None = None
slots:
    default: Markup
imports:
    - from myapp.utils import truncate
---
<a class="card" href={href or '#'}>
    <h2>{title}</h2>
    <p>{truncate(children, 200)}</p>
</a>
```

Compiles to roughly (illustrative — exact emission is a Phase 5a deliverable):

```python
# Compiled from html/components/card.html
# DO NOT EDIT — regenerate with `plain html compile`.
from __future__ import annotations
from plain.html._runtime import escape_html, escape_attr, Markup
from myapp.utils import truncate

__template_source__ = "html/components/card.html"

def render(*, title: str, href: str | None = None, children: Markup = Markup(""), _ctx: dict) -> str:
    _out: list[str] = []
    _append = _out.append
    # line 9 col 1
    _append('<a class="card" href="')
    _append(escape_attr(href or '#'))
    _append('">\n    <h2>')
    # line 10 col 9
    _append(escape_html(title))
    _append('</h2>\n    <p>')
    # line 11 col 8
    _append(escape_html(truncate(children, 200)))
    _append('</p>\n</a>')
    return "".join(_out)
```

Key emission rules:

- **Text nodes** → string literals concatenated into adjacent `_append(...)` calls. Constant-fold runs of text together.
- **`{expr}` in text body** → `_append(escape_html(<expr>))`.
- **`{expr}` in attribute value** → `_append(escape_attr(<expr>))`; mixed segments emit a single concat. (Phase 6 picks the right escape per position; Phase 5 lands a pass-through `escape_html` / `escape_attr` that matches the interpreter's behavior byte-for-byte.)
- **Attribute with single `{expr}`** preserves the interpreter's boolean / list / `False` / `None` semantics via a runtime helper `_render_dyn_attr(name, value, _out)`.
- **`:if={cond}`** → wrap the node's emission in `if <cond>:`.
- **`:for={x in xs}`** → wrap in `for <targets> in <xs>:` with real Python unpacking.
- **`<template>` fragment** → emit children inline, no wrapper.
- **`<template :include="path">`** with literal path → call into the compiled child module: `_out.append(_inc_<n>.render(**_attrs, _ctx=_ctx, default=<slot_default>, header=<slot_header>))`.
- **`<template :include={expr}>`** dynamic path → runtime resolver: `_resolve_include(<expr>, _current=__template_source__).render(...)`.
- **Slot composition** → each slot's children render to a `Markup` string in the parent's frame, then get passed as kwargs to the child module.
- **`{# … #}` template comments** → skipped at emit (already preserved by parser for the formatter).

#### Module signature

```python
def render(*, _ctx: dict, **attrs) -> str: ...
```

- `attrs` come from `**kwargs` so an undeclared keyword raises `TypeError` only when frontmatter declares `attrs:` _and_ the call uses unknown keys. In practice, codegen emits a typed signature when `attrs:` is present, and a permissive `**attrs` signature when it isn't.
- `_ctx` carries view-level context (request, DEBUG, etc.) — the same dict that flows through `_render_include` today. Inside the function, attribute lookups for un-declared names fall through `_ctx`.
- Slot kwargs (`default`, named slots) arrive as `Markup`.

#### Cache

- Cache root: `<settings.path.parent>/.plain-html-cache/` by default; override via `PLAIN_HTML_CACHE_DIR` env var.
- Filename: `<sha256(source)[:16]>__<safe-template-name>.py`. Embed the template name for grep-ability; the hash is the cache key.
- Cache key inputs (any change invalidates):
    1. Source file SHA-256.
    2. Compiler version (a module-level constant bumped on codegen changes).
    3. For each `:include` _literal_ path that resolves at compile time: the resolved file's cache key, transitively.
    4. For modules referenced in `imports:`: source mtime. (Type references in `attrs:` annotations are checked separately by Phase 9's typecheck pipeline — Phase 5 does not need them in its key.)
- Atomic write: write to `<name>.py.tmp` + fsync + rename. Stale tmp files get cleaned on the next compile.
- Loader: `importlib.util.spec_from_file_location` with a stable module name like `_plain_html_cached_<hash>` so `importlib` caches the loaded module in `sys.modules` for the process lifetime.
- Dev-time invalidation: on `find_template()`, compare source mtime to cache mtime; recompile if newer. Production assumes precompiled.

#### Sub-phases

Sub-phases are ordered so each lands behind the `PLAIN_HTML_ENGINE` env-var switch and leaves the interpreter untouched until 5f.

**5a — Static codegen, no includes, no cache.** `plain.html.compiler.compile_tree(tree, fmdict, source_label) -> str` returns Python source. Function emits an in-memory `exec`'d module via `compile()`. No file IO. `engine.render_source(...)` gets a `use_compiler: bool = False` kwarg; tests flip it. Lands: text, `{expr}`, elements, attributes, `:if`, `:for`, `<template>` fragments, `HtmlComment` / `Doctype`. Defers: `:include`, slots, dynamic include, frontmatter `attrs:` typed signature.

**5b — Frontmatter `attrs:` + `imports:` in the emitted module.** Typed `def render(*, name: T, ...)` signature when `attrs:` is present; `imports:` block emitted at module top. Walrus / arbitrary Python expressions in `{...}` confirmed working via test.

**5c/5d — Static includes + slot composition (landed together).** Resolve `:include="literal/path"` at compile time. A `CompileSession` walks the include graph depth-first; each child is compiled before its parent, and child `render` functions are injected into the parent module's globals as `_inc_0`, `_inc_1`, … before exec. Slot children render to `Markup` strings in the parent's scope via per-slot sub-buffer accumulators, then pass to the child as kwargs (default → `children=` + `default=`; named slots route by `slot="..."`). `_root_ctx` threads through every include boundary so the view's original context (request, DEBUG, …) flows down without explicit re-passing. The 5c/5d split in earlier drafts was arbitrary — you can't exercise includes without slots, so they shipped as one merge.

**5e — Dynamic includes (`:include={expr}`) + cache to disk.** Runtime helper `_resolve_include(name, *, _current)` calls `loader.find_template(...)` + `_get_or_compile(path)` and returns the cached module. Cache moves from in-memory to `.plain-html-cache/`. Atomic write + load. Dev-mode mtime check.

**5f — Cutover.** Flip the default of `PLAIN_HTML_ENGINE` to `compiler`. Interpreter stays in the tree, gated by `PLAIN_HTML_ENGINE=interpreter`, as the byte-equivalence oracle for parity tests.

**5g — Delete the interpreter.** After ≥ one release with the compiler as default, the parity test is dead weight and the interpreter is unmaintained code. Delete `engine.py`'s `_render_*` helpers; keep only the thin entry that delegates to the compiler.

#### Performance gate

Add `plain-html/tests/internal/test_compiler_perf.py`, runs in CI:

- Compiles all 5 bench cases.
- Asserts compiled median per-case ≤ 2× Jinja median, with a generous absolute floor (no flakes on tiny cases where everything is sub-microsecond).
- The same bench cases run via `bench/render.py` for ad-hoc human inspection. Both share fixture data so CI numbers are reproducible locally.

If the gate trips after a future change, it's a real regression — investigate before merging.

#### Test strategy

1. **Unit tests per construct** (`tests/internal/test_compiler.py`): for each emission rule above, assert the generated Python source contains the expected fragment _and_ `exec()`s to produce the expected output. Source-fragment assertions are coarse (substring matches) so cosmetic codegen changes don't churn the suite.

2. **Corpus byte-equivalence** (`tests/internal/test_compiler_parity.py`): for every `.html` in the repo, render via interpreter and compiler with a shared fixture context (`{name: "Dave", items: [...], request: <fake>}`, etc.), assert `interp_out == compiled_out`. Templates that need richer context get per-template overrides in a small YAML sidecar. This is the hard invariant — landing 5a through 5d without this would be reckless.

3. **Include-graph invalidation** (`tests/internal/test_compiler_cache.py`): write three templates A → B → C in a temp dir, compile, modify C, recompile, assert A's cache was rebuilt.

4. **Traceback mapping** (`tests/internal/test_compiler_traceback.py`): compile a template whose `{expr}` raises at runtime; assert the traceback frame's filename + line point at the original `.html` source. Achieved via `# line N col M` comments + `compile(src, "html/foo.html", "exec")` filename.

#### Open questions

- **Codegen target — string emit or AST?** String-template emission is simpler, easier to debug visually, and Python's `compile()` swallows the parse cost trivially. AST builder (`ast.Module(...)`) is hygienic but heavier. Lean toward string emission; revisit if string escaping bugs accrete.
- **Constant-folding text runs.** Adjacent text nodes collapse into one literal at compile time. Cheap, big win on whitespace-heavy templates. Land it in 5a.
- **Single big `_out.append(...)` vs `_append = _out.append` local alias.** The local alias is a known micro-trick (saves an attribute lookup per call). Plain string-concat with `+=` is slower than `.append` + `"".join` for long sequences. Benchmark in 5a; pick whichever wins.
- **`Markup` arrives where?** Phase 6 introduces real per-position escape functions; Phase 5 emits placeholders (`escape_html`, `escape_attr`) that match interpreter behavior byte-for-byte. Keep the names stable so Phase 6 is a function-body swap, not a codegen change.
- **`{x}` in `<script>` / `<style>`.** Compile-time error per spec. Already parse-rejected? Verify in 5a; raise `CompileError` if not.

#### Risks + mitigations

| Risk                                                              | Mitigation                                                                                                                                                           |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Compiled output diverges silently from interpreter on edge cases. | Corpus parity test (test #2) runs in CI; covers every template in the repo with a real fixture context. Drift is loud.                                               |
| Cache invalidation bug → stale render.                            | Hash-based key + transitive include keys make this hard to hit. Dev mode mtime-checks on every render. Add a `plain html cache clear` subcommand for the panic case. |
| `imports:` runs arbitrary Python at compile time.                 | Same trust model as today — `imports:` runs at render time in the interpreter. No new attack surface.                                                                |
| Slow first request (compile-on-demand).                           | Provide `plain html compile` to precompile everything ahead of time; document for production deploys. Cold compile time is bounded — the corpus is small.            |
| Traceback frames are unreadable.                                  | Test #4 enforces source-mapping. Generated comments + `compile(..., filename=template_path, ...)` give Python what it needs.                                         |
| Compiler becomes a maintenance hot spot.                          | Sub-phase 5g deletes the interpreter once parity is durable. Two engines is a temporary cost, not a permanent one.                                                   |

#### Success criteria

- All five sub-phases land. Each is independently mergeable behind `PLAIN_HTML_ENGINE`.
- Corpus parity test green: every repo template renders identically under both engines.
- Perf gate met: compiled median ≤ 2× Jinja on every bench case.
- Tracebacks from `{expr}` exceptions point at `template.html:line:col`.
- `bench/render.py` shows the closed gap; the `+tree+expr` columns become uninteresting and can be removed once the interpreter is deleted.

---

### Phase 5.5 — Security hardening (before 5f cutover)

Sits between Phase 5's compiler work and Phase 5f's cutover. The full contextual-autoescape design lives in Phase 6, but a few sharp edges shouldn't ship to the compiler default with stub escape functions. These are small, mostly compile-time checks that fail loud rather than silently producing exploitable output.

#### Threat model

| Boundary                                                       | Trust                        | Notes                                                                                                           |
| -------------------------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------- |
| User data flowing into `{expr}`                                | Hostile by default           | Escape every `{expr}` per position. Phase 6 lands the full per-context table; 5.5 closes the worst sharp edges. |
| Template author code (`imports:`, `{python expr}`, `:include`) | Trusted (same as `views.py`) | No sandbox. Out of scope.                                                                                       |

Plain.html does **not** support running untrusted templates. The trust model matches Django/Jinja: template authors are application code authors. Documented in `plain-html/README` as part of this phase so users aren't surprised.

#### Deliverables

1. **Reject `{expr}` inside `<script>` / `<style>` bodies at compile time.** One-line check in `_emit_element`. Authors who genuinely need to inject data into JS use `Markup(json.dumps(value))` and document the call site. The error message points there.
2. **Reject `on*={expr}` event-handler attributes** with the default escape policy. JS execution context; HTML-escape does nothing. Author must explicitly wrap the value in `mark_safe(...)` (which the spec already treats as a deliberate opt-out for any escape).
3. **Stub `escape_url` for known-URL attributes** (`href`, `src`, `action`, `formaction`, `xlink:href`). 5.5 doesn't have to land the full URL validator — even a thin stub that rejects `javascript:` and `data:text/html` scheme prefixes closes the cheap exploit. Phase 6 expands it.
4. **Verify YAML safety.** Confirm `python-frontmatter` uses `yaml.safe_load`. If not, force-route through `safe_load`. Unsafe YAML loading anywhere on the compile path is RCE-on-package-install.
5. **Trust-model section in `plain-html/README`.** Explicit "we don't sandbox templates; don't render user-uploaded templates with this engine; here's what attacker-controlled DATA gets escaped vs. what doesn't."

Cache permissions (mode `0700` + atomic rename) and dynamic-include path-traversal refusal (`:include={expr}` must stay under configured `html/` roots) belong to Phase 5e itself — call them out there in the deliverables.

#### Success criteria

- `<script>{x}</script>` and `<style>{x}</style>` are compile errors with a message pointing at the `Markup(json.dumps(...))` workaround.
- `<a onclick={handler}>` is a compile error unless `handler` is statically `mark_safe(...)` at the call site (compile-time check, not runtime).
- `<a href={url}>` with `url = "javascript:alert(1)"` renders the attribute as empty (or raises) — not as a clickable XSS.
- README has a "Security" section covering the trust model and the per-position escape table.
- `python-frontmatter` is confirmed (in code or via pinned version note) to use safe YAML loading; a regression test asserts that a YAML payload containing `!!python/object/apply:os.system [...]` fails to parse.

#### Risks + mitigations

| Risk                                                              | Mitigation                                                                                                                                                                 |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `escape_url` stub is too permissive — misses some scheme variant. | Whitelist-by-scheme, not blacklist. Allow `http`, `https`, `mailto`, relative paths; everything else routes through a small `is_safe_url(s)` helper. Phase 6 hardens this. |
| Author can't legitimately put dynamic data into `<script>`.       | Document the `Markup(json.dumps(...))` pattern in the README and the compile-error message. Real use cases (CSRF token, feature flags) are well-handled by this.           |
| Tighter checks break templates already in `example/`.             | Phase 10 migration grep will surface these; fix per-template as we go. Bound — the example corpus is small.                                                                |

---

### Phase 6 — Contextual autoescape

Deliverables:

- `plain.html.escape` module with per-position escape functions: `escape_html`, `escape_attr`, `escape_url`, `refuse_script`, `refuse_style`.
- Compiler picks the right escape function based on the expression's position in the tag tree.
- URL escape validates scheme — rejects `javascript:`, `data:` text/html.
- `Markup` (from Phase 1) bypasses escape.
- `{x}` inside `<script>` / `<style>` body is a compile error (caught at Phase 3 already; this phase confirms it through the compiler).

Success criteria:

- `{user.name}` in text body → HTML-escaped.
- `{user.profile_url}` in href → URL-validated and escaped.
- `{x}` inside `<script>` body → compile error.
- Unit tests for each context, including XSS attempt strings (`"><script>`, `javascript:alert(1)`, `<img onerror=...>`).

---

### Phase 7 — Template loader, env-var routing, and parity harness

Deliverables:

- `plain.html.loader` module wrapping a FileSystemLoader-style discovery.
- Configured via `TEMPLATES` setting (or extends the existing one), with each entry having both `templates_dir` and `html_dir` paths.
- When env var `PLAIN_HTML_RENDERER=new` is set, the loader prefers `html/<path>.plain` over `templates/<path>.html` for any template name.
- Falls back to Jinja's existing loader if no `.plain` version exists.
- Cross-engine `:include` is forbidden: a `.plain` template's `:include` resolves only within `html/` dirs; never falls back to a Jinja template.
- Search-path precedence: project's app dir first, then package dirs in INSTALLED_PACKAGES order.
- Relative paths (`./foo`, `../bar`) in `:include` resolved relative to the calling template's directory.

**Parity harness** (the major new addition vs v1 of this plan):

- New directory `tests/parity/` at repo root (or under `plain.html/tests/`).
- A fixture file (Python or YAML) lists `(route, user_id=None, method="GET", data=None)` tuples.
- A pytest test parametrized over the fixture: for each route, runs `uv run plain request` under both env-var states, normalizes inter-tag whitespace, asserts equivalence.
- A sidecar `parity_allowlist.yml` records intentional per-route differences (regex or structural) with rationale; assertions tolerate matches in the allowlist but flag drift.
- Runs as part of `./scripts/test` and `./scripts/pre-commit`.

Success criteria:

- With env var off: behavior identical to before.
- With env var on: `.plain` templates found and rendered; Jinja templates still work for un-ported templates.
- Per-package overrides work (`app/html/admin/login.plain` shadows `plain.admin/html/admin/login.plain`).
- Parity harness runs (even with an empty fixture list) and is wired into `./scripts/test`.
- Unit tests for resolution order, overrides, relative paths, cross-engine-include refusal.

---

### Phase 8 — `plain html check` — structural validation

Deliverables:

- `plain html check <path>` CLI command (added in `plain.html.cli`). Accepts a file, a directory, or `--all`.
- Walks one or more `.plain` files; for each:
    - Parses frontmatter (Phase 2)
    - Tokenizes (Phase 3)
    - Builds tag tree (Phase 4)
    - Validates: HTML balance, void-element children, `:include` paths resolve to existing files, slot routing matches included template's `slots:` declarations, attrs passed match the included template's `attrs:` declarations (required present, no unknown), `:if` / `:for` shape sanity.
- Reports errors with `file:line:col`, human-readable messages.
- Exit code 0 on success, non-zero on errors.
- Integrated into `./scripts/check` as a step (off by default until Phase 10 begins porting templates; flips on when the first `.plain` file ships).

Tier 2 (WHATWG content-model) and Tier 3 (a11y) rules from the spec are **deferred to Phase 17** — flagged in the README's "Roadmap" so users know they're coming but not required for v1 migration.

Success criteria:

- Malformed templates produce useful error messages.
- Valid templates pass cleanly.
- Integration test: run on a fixture directory with known-good and known-bad templates.

---

### Phase 9 — `plain html check` — type checking via ty

Deliverables:

- Extended `plain html check` that runs type validation on every `{expr}` in the template.
- Implementation:
    - For each template, synthesize a Python module containing:
        - The `imports:` block as real imports
        - A function signature derived from `attrs:` declarations (real type hints)
        - Inside the function body: each extracted expression appears as a typed statement (e.g., `_ = expr  # template <relpath>:<line>:<col>`)
    - Write synthesized module to a temp file.
    - Invoke `ty check <temp_file> --output-format gitlab` (or the structured format the pinned ty version supports).
    - Parse the JSON output, map errors from synthesized-file positions back to template positions via the stored source map.
    - Report errors in the Phase 8 style.
- **Result caching**: each template's check result cached keyed on
    - template content hash
    - resolved-type-reference module mtimes (from `attrs:`)
    - `imports:` module mtimes
    - ty version pin
      Avoids re-running ty on unchanged templates; matters during full-repo checks.
- Backend abstraction (`plain.html.typecheck.backends`) so pyright can be plugged in as an alternative if ty is unavailable.
- Pin ty to a specific version in `plain.html/pyproject.toml`. Alpha tools break; revisit the pin only deliberately.
- Scoped-slot `yields:` declarations participate: a `:as={var}` binding gets the declared `yields:` type in the synthesized scope.

Success criteria:

- Template referencing a nonexistent prop attribute fails type check.
- Template passing a wrong-typed literal to a typed `:include` fails type check.
- Template with correct usage passes.
- Re-running the check on unchanged files completes in O(open-file) time (cache hit, no ty subprocess).
- Integration test exercising the full pipeline against fixture templates.

---

### Phase 9.5 — `plain html format`

**Goal**: ship a formatter before migration begins in earnest (Phase 10), so each ported template gets formatted as it lands and the corpus stays consistent.

Prereq: Phase 3 amendment landed — `TemplateCommentToken` is preserved through tokenize/parse. Without it, the formatter erases author comments.

Deliverables:

- `plain html format <path>` CLI command (write mode) and `plain html format --check <path>` (CI mode; nonzero exit if any file would change).
- Walks one or more `.plain` files; for each:
    - Parses frontmatter (Phase 2), tokenizes (Phase 3), builds tag tree (Phase 4).
    - Pretty-prints the body using a doc-tree printer (Wadler-style) over the parsed nodes.
    - Re-emits the frontmatter block **byte-for-byte unchanged**.
- Whitespace-sensitivity model derived from WHATWG content categories. Inline (phrasing-content) elements never get newlines injected inside or around them; block elements wrap freely; `<pre>`/`<textarea>`/`<script>`/`<style>` bodies are verbatim. The classification table ships in `plain.html.format.whitespace`.
- Attribute wrapping: single line until the tag exceeds 88 columns, then one attribute per line, aligned under the tag name; closing `>` on its own line.
- Quote normalization, boolean-attribute normalization per the decisions table above.
- `{...}` interiors are opaque — the formatter never edits Python source inside an expression.
- Reads stdin / writes stdout when path is `-`, for editor integration.
- Wired into `./scripts/fix` (format mode) and `./scripts/check` (check mode).
- Prior art for implementation reference: `prettier-plugin-astro`, `djLint`, prettier's `language-html/`.

Success criteria (each gates the phase):

1. **Idempotency property test**: `format(format(x)) == format(x)` holds across every `.html` file in the repo's corpus, and across a hand-curated set of pathological inputs (deeply nested inline elements, mixed inline/block, long attribute lists, `<pre>` with embedded `{expr}`, `<script>` containing `{`-like JS, comment-heavy templates).
2. **Render-equivalence property test**: for every `(template, context)` fixture in the parity harness (Phase 7), `render(format(template), ctx) == render(template, ctx)`. The parity harness is reused here; this is the hard invariant.
3. **Comment preservation**: `{# … #}` and `<!-- … -->` survive round-trip.
4. **Performance**: format the entire monorepo's `.html` corpus in under 2 seconds wall-clock; format a single typical template in under 10 ms (warm).
5. **No bytes-inside-`{}` changes**: assertion in tests that for every expression token, the bytes between its `{` and `}` are identical pre- and post-format.
6. **Frontmatter untouched**: assertion in tests that the bytes from start-of-file to the end of the frontmatter delimiter are identical pre- and post-format.

Conformance test layering (per the **Conformance test strategy** section above): success criteria 1, 2, 5, and 6 are implemented as the repo-corpus property test (tier 1). The hand-curated pathological inputs in criterion 1 live in the golden-snapshot corpus (tier 3) — grow it as bugs surface, mirroring Prettier's `tests/format/html/` layout. html5lib DOM comparison (tier 2) backs criterion 2 when regex normalization isn't strong enough.

Non-deliverables (explicitly deferred):

- Class-attribute sorting (Tailwind-aware or otherwise). Tracked as a follow-up.
- Expression-interior formatting (running ruff over `{...}` contents). Tracked as a follow-up.
- Tier-2/Tier-3 lint rules (those stay in Phase 17).

---

### Phase 10 — Port `example/` app

Deliverables:

- **Inheritance order**: before porting, run `grep -r '{% extends\|{% include' example/app/templates/` to build the dependency graph. Port layouts first, then partials, then pages in dependency order. No cross-engine includes are permitted, so each layout's full descendant tree must port in a single batch.
- Every template in `example/app/templates/` ported to `example/app/html/`, with `.plain` extension.
- Presenters added per the upfront-decisions convention wherever template-side logic moves to Python (`{% if %}` chains, `{% set %}` computations, complex filter chains). Each presenter lives in `app/presenters.py` or `app/<feature>/presenters.py` and is constructed by the view.

Each ported route gets a fixture entry added to `tests/parity/fixtures.yml`. The parity harness must remain green throughout the phase.

Success criteria:

- For every route in `example/`:
    - Parity harness asserts output equivalence under both renderers (whitespace-normalized).
    - Intentional differences (if any) are recorded in `parity_allowlist.yml` with rationale.
- `uv run plain html check example/app/html/` passes with no errors.
- All example tests pass with the new renderer enabled.

Verification (per-template, run by the harness in CI):

```bash
PLAIN_HTML_RENDERER= uv run plain request /users > /tmp/old.html
PLAIN_HTML_RENDERER=new uv run plain request /users > /tmp/new.html
# Harness normalizes and asserts; manual diff only needed when an allowlist entry is being authored.
```

---

### Phase 11 — Port `plain.admin` form components (14 elements)

Deliverables:

- All 14 element templates in `plain-admin/plain/admin/templates/elements/admin/` (`Input.html`, `InputField.html`, `Icon.html`, `Submit.html`, etc.) ported to `plain-admin/plain/admin/html/components/admin/` as `.plain` files (snake_case filenames).
- Each new component file has `attrs:` declarations matching what the Jinja element accepts.
- Existing element templates remain (other un-migrated templates may still reference them).

Success criteria:

- `uv run plain html check plain-admin/plain/admin/html/` passes.
- Each component can be invoked from a test template and renders correctly.
- Unit tests covering each component's typed attr validation.
- Parity harness picks up any admin route that already uses these components and stays green.

---

### Phase 12 — Port `plain.admin` pages

Deliverables:

- **Layouts first** (`admin base`, sidebar, auth layouts), then list views, detail views, settings pages in dependency order.
- Every `plain.admin` page template ported to `html/` as `.plain`.
- Presenters added for pages whose templates contained meaningful logic.

Success criteria:

- Walking through the admin UI under `PLAIN_HTML_RENDERER=new` works visually equivalently.
- Parity harness green for every admin page.
- `uv run plain html check plain-admin/plain/admin/html/` passes.

---

### Phase 13 — Port `plain.admin` data browser

Deliverables:

- The data browser templates ported. This is the most htmx-heavy section; **the Phase 0 tracer bullet should have already exercised one fragment from this area**, so engine gaps here should be minor. Any remaining gaps surface here — pause migration, fix `plain.html`, add tests, resume.

Success criteria:

- Full data browser workflow (list → filter → detail → edit → save) works under the new renderer.
- Parity harness green for static parts; interactive flows (htmx swaps, OOB updates) manually exercised once and recorded as a smoke-test checklist in `MIGRATION_NOTES.md`.

---

### Phase 14 — Port remaining in-repo packages

Deliverables:

- Any other package in the repo with a `templates/` directory ported to `html/`:
    - `plain.toolbar`
    - `plain.dev`
    - `plain.observer` (if it has templates)
    - `plain.pages`
    - `plain.flags` (admin toolbar panel)
    - Anything else found by `find plain* -type d -name templates`
- Each package: layouts first, then descendants. Old `templates/` remain for now.

Success criteria:

- Each package's tests pass under both renderers.
- `uv run plain html check` passes for each package's `html/` dir.
- Parity harness covers each package's user-facing routes.

---

### Phase 15 — Final parity sweep and remaining smoke tests

Deliverables:

- Repo-wide test pass under `PLAIN_HTML_RENDERER=new`.
- Aggregated migration notes consolidated into a single document listing all entries from `parity_allowlist.yml` with their rationales (the long-form record of intentional differences).
- Manual smoke test pass on example + admin under the new renderer — recorded as a checklist.

Note: the parity harness has already been in place since Phase 7, so this phase is reconciliation, not standing up new infrastructure.

Success criteria:

- `./scripts/test` passes with env var both off and on.
- `./scripts/check --skip-test` passes with env var on.
- Manual smoke test: example app and admin both work end-to-end under the new renderer.

---

### Phase 16 — Remove the old engine

Deliverables:

- All `templates/` directories deleted (or renamed to `html/` after final review).
- Jinja-based loader removed from `plain.templates`; package becomes a shim that re-exports `plain.html` per the upfront decision (preserves any user imports like `from plain.templates import ...`).
- Jinja2 dependency dropped from `plain/pyproject.toml`.
- `PLAIN_HTML_RENDERER` env var removed (no longer needed).
- Parity harness either retired or repurposed: drop the env-var dimension and keep it as a route-level snapshot test against `.plain` output only. Decide based on whether the snapshots provide ongoing regression value.
- All references to "Jinja" in framework docs replaced with the new engine's terminology.
- Optional: rename CLI from `plain html check` to `plain template check` to match the spec, if `plain.templates` is the package users will reach for.

Success criteria:

- `./scripts/test` passes.
- `./scripts/check` passes.
- `grep -ri "jinja" plain* example/` returns only historical/changelog references.
- The example app and admin both work without env vars.

---

### Phase 17 — Post-migration HTML lint tiers (deferred, optional)

**Out of v1 migration scope** but explicitly on the roadmap per the spec's "HTML correctness" section. Four independent workstreams, shipped as separate sub-phases (17a–17d), not one PR. Order matters because 17a establishes the rule-engine pattern that 17b reuses; 17c/17d are formatter features and can ship in either order after 17a.

Rule-code scheme (decided in the formatter/linter decisions table above):

- `PH0xx` — syntax & structure (Phase 8, already shipped).
- `PH1xx` — content model (17a).
- `PH2xx` — accessibility (17b).
- Config under `[tool.plain.html]` in `pyproject.toml`, per-rule severity (`error` / `warning` / `off`). Same scheme ruff uses.

#### Ecosystem data sources (researched)

| Domain              | Source                                                                                                | Integration                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| HTML5 content model | `html-validate`'s `html5.json` (~150KB, MIT) — the only maintained machine-readable transcription     | Vendor under `plain-html/plain/html/lint/_data/html5.json`, document provenance, sync per release |
| ARIA 1.2            | `aria-query`'s `roles.json` + per-characteristic JSON (MIT, A11yance org)                             | Vendor the JSON files; no maintained Python equivalent                                            |
| Tailwind class sort | `rustywind` (Rust binary; reads canonical order from project's generated CSS via `--output-css-file`) | Shell out — reimplementing Tailwind v4 config resolution is a doomed project                      |
| Python formatting   | `ruff format --stdin-filename foo.py -` (no public Python API per Astral discussion #12351)           | Shell out once per template, not once per expression                                              |

Explicitly **not** doing: Nu HTML Checker (vnu.jar) backend — html-validate's data vendored in-process covers the same ground without a Java dep. Render-then-validate adds no signal static analysis doesn't already provide.

---

#### 17a — Tier-2 content-model rules (`PH1xx`)

WHATWG nesting rules (`<p>` content model, `<a>` non-nesting, `<button>` interactive content, `<table>` structure, `<ul>`/`<ol>` children, `<dl>`/`<head>` content), required attributes (`<a href>`, `<img alt>`, `<input type>`), attribute value validity (`<input type="...">`, `<meta charset>`, `<link rel>`), duplicate-id detection.

Rule engine: a second walker over the existing tag tree, separate from `plain html check`'s structural pass. Each rule is `(code, severity, predicate)`. Walker yields diagnostics with the existing `file:line:col` shape so output is uniform with Phase 8.

plain.html-specific wrinkles (the actual design work):

1. **`<template :if>` / `<template :for>` are transparent.** Their children become children of the surrounding context for content-model purposes. `<p><template :for="x in xs"><div/></template></p>` flags `<div>`-in-`<p>` as `PH101`. The walker treats `<template>` directive nodes as see-through.
2. **`<template :include>` is opaque.** Don't recurse across include boundaries — too brittle, especially with dynamic `:include={expr}`. Document the limitation in the rule's docs. Statically-resolvable include recursion can come later as opt-in.
3. **Dynamic IDs.** `id="{expr}"` skips duplicate-ID check. Literal `id="foo"` inside a `:for` block gets its own rule (`PH103` — "literal id inside loop"). Literals at the same template-static position dedupe normally.
4. **Constrained attribute values with `{expr}`.** `type="{x}"` skips the enum check; `type="button"` is checked.

Success criteria: rule set covering the deliverable list above runs cleanly against the in-repo corpus; each rule has unit tests for hit/miss cases plus a documented opt-out via config.

---

#### 17b — Tier-3 a11y rules (`PH2xx`)

Warnings by default, off-able per rule. Initial small high-signal set:

- `PH201` — `<img>` missing `alt` (a11y-flavored message; structurally already covered by 17a's required-attribute check)
- `PH202` — `<button>` with no accessible name (no text content, no `aria-label`, no `aria-labelledby`)
- `PH203` — heading-level skip within a static document (warning; skipped when conditional structure makes static analysis ambiguous)
- `PH204` — invalid ARIA role / attribute / attribute-value
- `PH205` — `<input>` with no associated `<label>` (matching `for=`/`id=` static pair, or wrapped)

Deferred from initial cut: full role/attribute compatibility matrix from aria-query (e.g. "role=button requires tabindex" deep rules). Too much false-positive surface; revisit after 17b's small set has real-world calibration.

Success criteria: each rule has unit tests; running 17b on the in-repo corpus produces a calibrated baseline (zero false positives after rule tuning, real findings on templates known to have a11y gaps).

---

#### 17c — Expression-interior formatting (formatter follow-up)

Run ruff over `{...}` bodies. Idempotency from Phase 9.5 must still hold.

Mechanics: extract every `{expr}` in the template, emit a synthesized `.py` file using the same pattern Phase 9's typecheck already uses:

```python
# line 12 col 5
_ = (user.name)
# line 14 col 8
_ = (truncate(post.body, 200))
```

Shell out to `ruff format --stdin-filename <template>.py -` once per template (not once per expression). Parse the formatted output back, splice each formatted expression into the template at its original position. Source map already exists from Phase 9 — reuse it.

Idempotency: ruff is idempotent on Python, the splice is byte-exact, so the round-trip is idempotent by construction. Add a property test in the existing conformance suite. Cache by template content hash + ruff version.

Edge cases:

- Walrus inside `{}` — ruff handles it.
- Multi-line expressions — wrap in parens for synthesis, unwrap after.
- Comments inside `{}` — ruff preserves them.

Success criteria: every `.html` in the corpus round-trips identically after format → render-equivalence still holds → second format is a no-op.

---

#### 17d — Tailwind class sorting (formatter follow-up)

Shell out to `rustywind` (Rust binary, single static executable). Wrap install via a vendored binary or pip wrapper.

Why not Python: Tailwind v4 resolves sort order from the project's actual CSS pipeline. Reimplementing config resolution is a doomed project. `rustywind --output-css-file <project's generated css>` reads the canonical order from the rendered CSS and applies it — that's exactly the integration we want.

Activation: opt-in via `[tool.plain.html] tailwind_sort = true` in `pyproject.toml`. Not default-on; many projects don't use Tailwind.

Wiring: runs inside `plain html format` as a post-pass over the parsed tree's `class="..."` attribute values. Skip any value containing `{expr}` (can't sort a string we don't fully know).

Idempotency: rustywind is idempotent; sort + sort = sort. Property test in the existing suite.

Success criteria: opt-in flag flips behavior cleanly; format-check passes on a Tailwind project after one normalization pass; templates without Tailwind classes are unaffected.

---

Sequenced post-migration so the engine can stabilize first; users get a clean v1 without lint-rule churn. Promotes the "type checker for embedded Python" pitch into the spec-claimed "linter for HTML + Python."

---

## Definition of done

Plan complete when:

1. No `.html` Jinja templates remain in the repo (only `.plain` files).
2. No Jinja dependency in `plain/pyproject.toml`.
3. The `PLAIN_HTML_RENDERER` env var has been removed.
4. `./scripts/test`, `./scripts/check`, and `./scripts/pre-commit` all pass.
5. The example app and `plain.admin` both work end-to-end.
6. `plain html check` passes across all `.plain` files in the repo.
7. `plain html format --check` passes across all `.plain` files in the repo (every template is in canonical form).
8. The parity harness is either retired or repurposed as a snapshot suite; either way it is intentional, not lingering.

## Risk register

- **Engine gaps discovered late** (likely during admin data browser, Phase 13). Mitigation: **Phase 0 tracer bullet** drives the hardest template through the full pipeline before Phase 1 even starts, so by the time Phase 13 arrives the htmx surface area is mostly known. Each phase remains reversible.
- **Significant rendering differences between old and new** for templates relying on Jinja-specific behavior. Mitigation: automated parity harness from Phase 7 catches each difference at the moment it appears; agent records each as bug-to-fix or intentional-improvement with rationale in `parity_allowlist.yml`.
- **Performance regression in the new renderer**. Mitigation: don't optimize before parity; benchmark after Phase 15; profile if needed.
- **Type-checker (ty) instability**. Mitigation: pin a specific ty version in `plain.html/pyproject.toml`; pyright fallback per Phase 9; result caching reduces dependency on subprocess speed.
- **Cache invalidation bugs around `:include` graph**. Mitigation: tests in Phase 5 specifically exercise transitive-include invalidation. If it gets flaky, the agent can wipe `.plain-html-cache/` and re-run — no correctness lost, only recompile cost.

## Rip-out plan (post-merge addendum)

The migration above was designed to run two engines in parallel for a long
window. Decision reversal: we're going option-3 instead — there is no
permanent two-engine cohabitation. plain-templates exits as a package.

End state:

- **Extension** is `.html`, not `.plain.html`. Editors highlight as HTML
  automatically; no infix needed once Jinja is gone.
- **Directory** is `html/`, not `templates/`. Each package has a
  `<pkg>/html/` directory containing only plain.html templates.
- **No per-package `templates.py` / `html.py` registration file.**
  plain.html templates declare what they use via frontmatter `imports:`.
  The only persistent registry is plain.html-core defaults (`url`,
  `asset`, request helpers) — small and stable.
- **`TemplateView` family** (`TemplateView`, `FormView`, `DetailView`,
  `ListView`, `UpdateView`, `DeleteView`) lives in
  `plain-html/plain/html/views.py`. Core only ships `View` and
  `Response`.
- **Direct callers** (toolbar items, admin value rendering, htmx
  fragments, error page) call `plain.html.render(path, ctx)` — the
  `plain.templates.Template` shim goes away.
- **Non-HTML rendering** (email subjects, plain-text bodies, any other
  string templating) uses Python f-strings or t-strings. No template
  engine indirection for non-HTML.

Sequence (option-3 rip-out):

1. **Loader standalone** — `plain.html.loader` owns its own
   `get_html_dirs()` discovery (walks `<package>/html/`). Drop the
   `from plain.templates.jinja.environments import get_template_dirs`
   import. Lookup keys are `<name>.html` in `html/`; transitional
   fallback to `<name>.plain.html` in `templates/` while packages
   migrate.
2. **Per-package migration recipe** — one package at a time,
   smallest-surface first (plain-tailwind, plain-htmx, plain-pageviews,
   plain-sessions, plain-email, plain-loginlink, plain-oauth,
   plain-pages, plain-support, plain-passwords, plain-toolbar,
   plain-admin, plain-observer, plain-flags, plain-jobs,
   plain-redirection, example): - `mv templates/<pkg>/foo.plain.html html/<pkg>/foo.html` - Delete the old `.html` Jinja sibling - Audit the template's `{...}` expressions; add an `imports:`
   frontmatter block for every helper that came from the global
   registry - Move any Python-side helper functions out of `_shims.py` into the
   package's normal module surface (so `from plain.tailwind import
tailwind_css` works from a template's `imports:` block) - Delete the package's `templates.py` once nothing references it
3. **Port the 14 remaining Jinja-only holdouts** (admin/ui.html,
   admin/\_base.html, observer main UI, toolbar inject + exception, the
   three admin model forms, the two card.html files,
   example/\_macros.html — likely refactor macros to Python helpers).
4. **Move `TemplateView` family** to `plain-html/plain/html/views.py`.
   Update ~50 view imports across the repo.
5. **Switch direct `Template(...)` callers** to `plain.html.render`.
   Drop `plain.templates.Template`.
6. **Build a plain.html fragment story** for the htmx
   `{% htmxfragment %}` mechanism (currently stubbed with
   `NotImplementedError` for `.plain.html`).
7. **Delete `plain-templates`** — Jinja runtime, env, extensions,
   filters, globals, registration APIs, views — all gone. Drop the
   workspace member, drop the dep from every package.
8. **`/plain-upgrade` rules** — rewrite `from plain.templates import …`
   → `from plain.html import …`, rewrite template paths in `Template()`
   / `TemplateView.template_name`, rewrite `.html` template-name
   strings if needed.

## Agent execution notes

- **One phase at a time.** Do not start Phase N+1 until Phase N's success criteria are met.
- **Phase 0 is not optional.** Skipping the tracer bullet risks discovering a fundamental design problem 12 phases in.
- **Layouts before descendants** within any migration phase. Use grep to build the dependency graph before starting.
- **Commit frequently.** Each logical step within a phase should be its own commit.
- **Write tests as you go.** Each module gets unit tests in `tests/internal/` and behavioral tests in `tests/public/` per the existing project conventions.
- **Ask before diverging.** If the design (in [plain-template-language](plain-template-language.md)) appears wrong or incomplete during implementation, surface it to the user before implementing a workaround.
- **Don't optimize prematurely.** Pure-Python end-to-end is the v1 target. Performance work is post-completion.
- **Don't bridge engines.** No cross-engine includes. Migration happens in coherent inheritance chunks.
- **Trust the parity harness.** If it goes red, stop and investigate; if it goes green and a manual smoke catches a real issue, add a fixture entry so the harness catches it next time.
