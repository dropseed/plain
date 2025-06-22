# Agents

This is the only AGENTS.md file in the repo -- you don't need to look for others.

When you need a `python` shell, use `uv run python`.

## Commands

- Run tests on all packages (or specify a package to test): `./scripts/test [package] [pytest options]`
- Lint and format code: `./scripts/fix`
- Make database migrations: `./scripts/makemigrations`

## READMEs

Inside each top level subdirectory is a `README.md` that is a symlink to the `README.md` in the of the Python package itself. You only need to edit the `README.md` inside of the package itself.

## Verifying changes

Not everything needs a test, but be liberal about using `print()` statements to verify changes and show the before and after effects of your changes. Make sure those print statements are removed before committing your changes.
