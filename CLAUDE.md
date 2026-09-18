# Claude

## After making code changes

1. **Format and lint**: `./scripts/fix` (always run this before committing)
2. **Run tests**: `./scripts/test [package]`
3. **Server tests**: Add `--server` when changes touch `plain/server/` or `tools/` server scripts

## Commands

Always use `./scripts/` commands from the repo root — never run `uv run plain fix`, `uv run plain pre-commit`, etc. directly in the `example/` directory.

| Command                       | Purpose                                                      |
| ----------------------------- | ------------------------------------------------------------ |
| `./scripts/fix`               | Format and lint code                                         |
| `./scripts/pre-commit`        | Full pre-commit validation                                   |
| `./scripts/test [package]`    | Run tests (add `--server` when changing `plain/server/`)     |
| `./scripts/server-test`       | Server conformance, load, and resilience tests               |
| `./scripts/create-migrations` | Create database migrations (calls `plain migrations create`) |
| `./scripts/type-check <dir>`  | Type check a directory                                       |

## Scratch directory

Use the `scratch` directory for temporary files and experimentation. This directory is gitignored.

## Testing changes

The `example` directory contains a demo app. Use `cd example && uv run plain` to test.

## Public vs internal tests

Tests split into `<package>/tests/public/` (the contract) and `<package>/tests/internal/` (the change detector) — read `.claude/rules/tests-layout.md` before adding tests.

## Backwards compatibility

Don't worry about backwards compatibility for API changes like function renames, argument changes, or import path updates. The `/plain-upgrade` skill integrates an AI agent into the upgrade process that can automatically fix user code during updates.

Deeper breaking changes that users can't directly control or fix in their own code still need careful consideration.

## Coding style

- Plain requires Python 3.13+ — use modern Python APIs and syntax freely (e.g. `X | Y` unions, `match`, `ExceptionGroup`, etc.)
- Prefer unique, greppable names over overloaded terms
- Verify changes with `print()` statements, then remove before committing

## CSP-safe by default (this repo's templates and assets)

Our shipped templates and assets must work under a strict CSP — no inline `style="..."`, no inline event handlers, `nonce` on inline `<style>`/`<script>`. See `.claude/rules/csp-safe.md`.

## Docs, rules, and skills

Plain ships three tiers of AI guidance per package — rules (always loaded guardrails), docs (package READMEs, read via `plain docs`), and skills (multi-step `/slash-command` workflows). Before editing any of them, see `.claude/rules/agent-guidance.md`.
