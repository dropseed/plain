# plain-testing changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-testing@0.1.0) (unreleased)

### What's changed

- Initial working engine: collection (`test_*` functions, `Test*` classes, async tests), assertion rewriting for bare `assert` with left/right values on failure, `@cases` expansion, `@skip`, `@tag` selection (`--tag`/`--exclude-tag`), `-k`/`-x`/`-v`, and failure output ending in a re-run command.
- `plain test` CLI, contributed through the `plain.cli` entry point group so it is available without `plain.runtime.setup()` (and therefore outside an app). Because nothing has set the runtime up by the time it runs, the runner makes the app-vs-library decision itself. `.env.test` loads via plain.dev's ladder when installed, with a minimal fallback otherwise.
- Test lifecycle extension point: packages register a `TestLifecycle` under the `plain.testing` entry point group. plain.postgres provides the automatic test database with per-test rolled-back transactions and `@isolated_db`; plain.email routes to the locmem backend and clears the outbox per test.
- Replaces `plain.pytest` — pytest is no longer supported. See the README's "Migrating from pytest" section.
