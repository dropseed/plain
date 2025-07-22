# Agents

This is the only AGENTS.md file in the repo -- you don't need to look for others.

## Commands and tools

- Open a Python shell: `uv run python`
- Run tests on all packages (or specify a package to test): `./scripts/test [package] [pytest options]`
- Lint and format code: `./scripts/fix`
- Make database migrations: `./scripts/makemigrations`

## READMEs

Inside each top level subdirectory is a `README.md` that is a symlink to the `README.md` in the of the Python package itself. You only need to edit the `README.md` inside of the package itself.

The README is the main written documentation for the package (or module). You can structure it using [`plain/assets/README.md`](/plain/plain/assets/README.md) as an example.

## Verifying changes

Not everything needs a test, but be liberal about using `print()` statements to verify changes and show the before and after effects of your changes. Make sure those print statements are removed before committing your changes.
