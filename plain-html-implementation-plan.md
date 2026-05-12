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

**Status: in progress.** A first cut lives in [`plain-html/`](plain-html/) with the parity harness in [`plain-html/tests/parity/`](plain-html/tests/parity/) (see that directory's README for the current parity diff and what it validates). The current scope is narrower than the deliverables above — paired self-contained Jinja and `.plain` fixtures rather than a real `plain.admin` data-browser fragment — but the engine surface is plumbed end-to-end (frontmatter → tokenize → tree → render with `:if`, `:for`, attribute interpolation, fragment templates, contextual HTML escape) and exhibits the kind of intentional-difference catalog the spec anticipated. Real-template parity (with includes, slots, and htmx attribute pass-through) lands as we expand the engine in Phases 2–7 and bring more fixtures online.

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

Deliverables:

- `plain.html.compiler` module that converts a tag tree into a Python source file containing a `render(...)` function.
- Generated function signature derived from frontmatter `attrs:` (typed kwargs).
- `imports:` block becomes top-of-module `from X import Y` / `import X` statements.
- Slot values arrive as kwargs (`children=`, `header=`, etc., type `Markup`).
- Tag tree walked recursively, emitting:
    - Text nodes → string literals
    - `{expr}` → escape-function call, chosen by position
    - `<template :include="path" attr={v}>` → loaded-template-function call
    - `<template :include={expr}>` → dynamic include via runtime path-resolution helper
    - `:if={cond}` → wrap node emission in `if cond:`
    - `:for={x in xs}` → wrap node emission in `for x in xs:`
    - `:as={var}` on slot template → captured in slot definition as a 1-arg callable
    - `<template>` fragment → emit children directly
- Walrus inside `{...}` works because it's just Python — confirm with a test.
- Compiled output written to `.plain-html-cache/<hash>.py`; loaded via `importlib`.
- **Cache invalidation graph** per spec: cache key includes
    - source file content hash
    - frontmatter-resolved type references (mtimes of modules referenced in `attrs:`)
    - `imports:` modules' source mtimes
    - **every `:include`d template's cache key**, transitively (rebuild a template when any descendant changes)
- Cached modules invalidate atomically; stale entries are removed when a key is regenerated.

Success criteria:

- Given a simple `.plain` template, compiles and renders correctly with the right inputs.
- Compiled output is readable Python (debuggable; positions in tracebacks map to template source via comments).
- Cache works: unchanged template doesn't recompile; changed template _or any of its includes_ does.
- Unit tests cover each tree construct + the transitive-include invalidation case.

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

**Out of v1 migration scope** but explicitly on the roadmap per the spec's "HTML correctness" section.

Deliverables (incremental):

- **Tier 2 — content model**: WHATWG nesting rules (`<p>` content model, `<a>` non-nesting, `<button>` interactive content, `<table>` structure, `<ul>`/`<ol>` children, `<dl>`/`<head>` content), required attributes (`<a href>`, `<img alt>`, `<input type>`), attribute value validity (`<input type="...">`, `<meta charset>`, `<link rel>`), duplicate-id detection within a rendered template.
- **Tier 3 — accessibility**: heading hierarchy, accessible names on `<button>`, ARIA attribute validity, form-label association. Warnings, off-able per rule.
- **Configuration**: ruff-style `[tool.plain.template-check.rules]` in `pyproject.toml`, per-rule severity.
- **Optional Nu Html Checker backend** for CI deep-checks.

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
7. The parity harness is either retired or repurposed as a snapshot suite; either way it is intentional, not lingering.

## Risk register

- **Engine gaps discovered late** (likely during admin data browser, Phase 13). Mitigation: **Phase 0 tracer bullet** drives the hardest template through the full pipeline before Phase 1 even starts, so by the time Phase 13 arrives the htmx surface area is mostly known. Each phase remains reversible.
- **Significant rendering differences between old and new** for templates relying on Jinja-specific behavior. Mitigation: automated parity harness from Phase 7 catches each difference at the moment it appears; agent records each as bug-to-fix or intentional-improvement with rationale in `parity_allowlist.yml`.
- **Performance regression in the new renderer**. Mitigation: don't optimize before parity; benchmark after Phase 15; profile if needed.
- **Type-checker (ty) instability**. Mitigation: pin a specific ty version in `plain.html/pyproject.toml`; pyright fallback per Phase 9; result caching reduces dependency on subprocess speed.
- **Cache invalidation bugs around `:include` graph**. Mitigation: tests in Phase 5 specifically exercise transitive-include invalidation. If it gets flaky, the agent can wipe `.plain-html-cache/` and re-run — no correctness lost, only recompile cost.

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
