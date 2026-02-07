# Development

## Dev Server

Run `uv run plain dev` to start the development server with auto-reload and HTTPS.

The server URL will be displayed (typically `https://<project>.localhost:8443`).

View logs: `uv run plain dev logs`

## Pre-commit Checks

Run `uv run plain pre-commit` after making changes to catch issues before committing. This runs code checks, preflight validation, migration checks, build, and tests.
