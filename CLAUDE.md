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

## Coding style

- Prefer unique, greppable names over overloaded terms
- Verify changes with `print()` statements, then remove before committing
