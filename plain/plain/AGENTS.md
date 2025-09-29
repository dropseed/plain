# Plain AGENTS.md

Plain is a Python web framework that was originally forked from Django. While it still has a lot in common with Django, there are also significant changes -- don't solely rely on knowledge of Django when working with Plain.

## Commands

The `plain` CLI is the main entrypoint for the framework. If `plain` is not available by itself, try `uv run plain`.

- `plain shell -c <command>`: Run a Python command with Plain configured.
- `plain run <filename>`: Run a Python script with Plain configured.
- `plain agent docs <package>`: Show README.md and symbolicated source files for a specific package.
- `plain agent docs --list`: List packages with docs available.
- `plain agent request <path> --user <user_id>`: Make an authenticated request to the running application and inspect the output.
- `plain --help`: List all available commands (including those from installed packages).

## Code style

- Imports should be at the top of the file, unless there is a specific reason to import later (e.g. to avoid circular imports).
