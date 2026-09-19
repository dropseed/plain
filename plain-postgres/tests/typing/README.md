# Typing corpus

Checker input, not pytest input. Nothing here runs; `uv run ty check` reading
these files _is_ the test, so no file is named `test_*.py` and pytest never
collects them.

Most of what typed construction and the typed `where()` API promise is static:
"this call is a type error." The only way to test that is to write the bad call
and assert the checker rejects it.

## The two assertions

**Must-reject** — write the offending call and mark it with the exact
diagnostic it has to produce:

```python
DefaultsExample(name=123)  # ty: ignore[invalid-argument-type]
```

The marker is the assertion. `unused-ignore-comment` is promoted to an error in
the root `pyproject.toml`, so the day that call stops being a type error the
suppression goes unused and `./scripts/type-check` fails. A wrong code fails
too: the real diagnostic is unsuppressed _and_ the marker is unused.

**Must-accept** — `assert_type` on the type that has to keep holding:

```python
assert_type(DefaultsExample.name, Field[str])
```

Plus any call that simply has to type-check clean; an unmarked line that starts
erroring fails the build on its own.

## How it runs

`./scripts/type-check plain-postgres` walks the whole package, `tests/typing/`
included, and `./scripts/type-validate` runs that for every fully typed path.
CI's `lint` job runs `type-validate`. There is no separate corpus script and no
separate ty invocation — the corpus is inside a gate that already exists.

`plain-postgres/tests` is on ty's `extra-paths`, so corpus files import the
example app's models (`app.examples.models.*`) the same way the runtime tests
do. Models that only exist to be mis-declared are defined inline.

## Adding a claim

1. Find the file for the area (construction, conditions, relations, field
   constructors) or add one — plain module name, no `test_` prefix.
2. Write the smallest call that expresses the claim, inside a `def` so the
   names stay local.
3. Must-reject: run `./scripts/type-check plain-postgres` with no marker first,
   read the code ty reports, and paste that code into the marker. Never guess
   the code.
4. Must-accept: `assert_type(...)`, or leave the line unmarked.
5. If the claim also has a runtime half (the call raises, or returns something
   specific), that half belongs in `tests/public/` or `tests/internal/` per
   `.claude/rules/tests-layout.md`. Cross-reference it in a comment.

## What this cannot catch

ty believes `types.pyi`. A stub that promises a keyword argument the runtime
constructor does not take, or declares a method under `TYPE_CHECKING` with no
runtime counterpart, type-checks perfectly and fails at runtime.
`tests/internal/test_stub_runtime_conformance.py` is the other half: it parses
the stub and compares it against the runtime objects.
