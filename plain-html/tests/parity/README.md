# Parity harness — Phase 0

End-to-end verification that the new `plain.html` renderer produces output equivalent to the current Jinja renderer for the same input. Drives the **tracer-bullet phase** described in [`plain-html-implementation-plan.md`](../../../plain-html-implementation-plan.md): we want to know — before broad migration work begins — whether the spec actually compiles down to byte-equivalent (or trivially-different) HTML.

## Layout

```
fixtures/
  <name>.html      # Jinja template
  <name>.plain     # plain.html template (same semantics)
  <name>.py        # `SCENARIOS = {name: factory}` mapping scenario name to context dict
results/           # Committed: outputs and diffs from the last run
parity_allowlist.yml  # Catalog of intentional differences with rationale
run_parity.py      # Harness: renders all fixtures × scenarios, writes results/
```

## Running

```bash
uv run python plain-html/tests/parity/run_parity.py
```

Exits non-zero if any normalized diff is non-empty.

## Current results (committed)

```
fixture/scenario      raw    normalized
---------------------------------------
greeting/one          match  match
greeting/many         match  match
greeting/none         match  match
tasks_list/populated  DIFF   DIFF
tasks_list/empty      DIFF   match

5 comparison(s), 1 normalized-diff failure(s).
```

Interpretation:

- **`greeting` (3/3 byte-identical)** — the engine produces byte-identical output to Jinja when the templates are written on a single line. Demonstrates parity at the level of text, expression interpolation, attribute interpolation, fragment conditionals (`<template :if>`), and HTML escape.
- **`tasks_list/empty` (normalized match)** — Jinja's `{% if %}` block syntax produces empty lines in the output that plain.html's element-level directives don't; whitespace-normalization erases the difference. See `parity_allowlist.yml` (`inter-tag-whitespace`).
- **`tasks_list/populated` (normalized DIFF)** — same whitespace difference as above, plus a real semantic difference: `data-done={task.done}` renders as `data-done` (when True) or omitted (when False) under plain.html, vs `data-done="True"` / `data-done="False"` under Jinja. See `parity_allowlist.yml` (`boolean-attribute-rendering`). This is the spec's intended HTML-aware boolean-attribute behavior, not a bug.

## What this validates

Phase 0 of the plan asks: "drive one realistic template through the full pipeline before broad infrastructure work begins." This harness covers:

- Frontmatter parse (`plain.html.frontmatter`)
- HTML-aware tokenize (`plain.html.tokenizer`)
- Tag-tree build with directive lifting (`plain.html.parser`)
- Tree-walk render with contextual escape (`plain.html.engine`, `plain.html.escape`)
- Iteration over real Python iterables (lists of dataclasses)
- Conditional rendering on truthy / falsy values
- Attribute interpolation, including single-expression and mixed-segment cases
- HTML escape on user-provided strings (`<spec>`, `Dave & Co`, `"the engineer"`)
- Boolean-attribute coercion per the spec's HTML-aware semantics

What is **not** validated yet (and remains for later phases per the plan):

- `<template :include>` invocations and slot composition (Phase 4–5)
- `:as` scoped slot binding (Phase 4)
- `<script>` / `<style>` opaque-body refusal (Phase 6)
- URL-attribute scheme validation (Phase 6)
- Compile-to-Python output path (Phase 5; Phase 0 uses an interpreter)
- Static `plain html check` (Phases 8–9)
- Cross-template cache invalidation (Phase 5)
- Real loader with `TEMPLATE_DIRS` precedence (Phase 7)

## Next steps

The plan's Phase 7 promotes this from a one-off script into a pytest-asserted harness that runs under `./scripts/test`, grows fixtures with each migration phase, and uses the allowlist to suppress documented differences while still printing them for review.
