# Claude

## After making code changes

1. **Format and lint**: `./scripts/fix` (always run this before committing)
2. **Run tests**: `./scripts/test [package]`

## Commands

| Command                      | Purpose                    |
| ---------------------------- | -------------------------- |
| `./scripts/fix`              | Format and lint code       |
| `./scripts/test [package]`   | Run tests                  |
| `./scripts/makemigrations`   | Create database migrations |
| `./scripts/type-check <dir>` | Type check a directory     |
| `uv run python`              | Open Python shell          |

## Scratch directory

Use the `scratch` directory for temporary files and experimentation. This directory is gitignored.

## Testing changes

The `example` directory contains a demo app. Use `cd example && uv run plain` to test.

## Backwards compatibility

Don't worry about backwards compatibility for API changes like function renames, argument changes, or import path updates. The `/plain-upgrade` skill integrates an AI agent into the upgrade process that can automatically fix user code during updates.

Deeper breaking changes that users can't directly control or fix in their own code still need careful consideration.

## Coding style

- Prefer unique, greppable names over overloaded terms
- Verify changes with `print()` statements, then remove before committing

## Rules and skills

This repo contains user-facing Claude rules and skills that ship inside each package. Users install them into their projects by running `plain agent install`.

- **Top-level `.claude/rules/` and `.claude/skills/`**: Used for developing _this repo_. These are what Claude sees when working here.
- **Package-level `<package>/plain/<module>/agents/.claude/`**: Shipped to end users. When editing these, the audience is the end user of that Plain package, not a contributor to this repo.

Many top-level rules and skills are exact copies of the package-level ones (e.g. `plain-models.md`, `plain-dev.md`, `plain-install`). The top-level copies exist so Claude has the same guidance when developing this repo. A few top-level skills (`annotations`, `readme`, `release`) are unique to development and have no package-level counterpart.

When editing a rule or skill, consider which copy you're changing. If the change is for end users, edit the package-level file in `agents/.claude/`. If the same change should also apply when developing this repo, update the top-level copy too.
