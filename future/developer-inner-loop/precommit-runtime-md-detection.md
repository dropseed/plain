# pre-commit: Detect runtime .md files before skipping tests

`plain pre-commit` now skips tests when only `.md` files are staged, but `.md` files aren't always docs. `plain-pages` renders markdown templates (`templates/pages/*.md`) through Jinja at runtime — edits to those files can introduce template/frontmatter regressions that tests would catch.

## Current behavior

`should_skip_tests()` in `plain-dev/plain/dev/precommit/cli.py` checks:

1. All staged files end in `.md`
2. None have `test` or `tests` as a path segment

This misses `.md` files that are runtime content (e.g. `templates/pages/*.md`).

## Possible approaches

- **Check for `plain-pages` in installed packages** — if the app uses `plain-pages`, don't skip tests when `.md` files under `templates/` are staged
- **Check against template dirs** — resolve configured template directories and see if any staged `.md` falls inside one
- **Broader heuristic** — only skip for `.md` files in well-known docs paths (repo root, `docs/`, `.claude/`, `agents/`) rather than skipping for all `.md` by default
- **Let users opt in/out** — a `[tool.plain.pre-commit]` config key listing paths or extensions that are "docs-only"

## Context

The skip logic was added to match what `scripts/pre-commit` already does at the shell level for this repo. The shell version is safe because this repo doesn't use `plain-pages`, but end-user apps might.
