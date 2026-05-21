---
name: plain-future
description: Opt a project into Plain's "future" channel — rolling unstable releases pulled from a github branch — or advance and apply upgrade notes. Use when the user wants to test in-progress Plain framework work, or to update an already-enabled future install.
---

# Plain future channel

The future channel points a project's Plain packages at a long-lived branch on `dropseed/plain` (default: `future`) instead of stable PyPI releases. It's how users opt into experimental work that hasn't graduated to a stable release.

## Enabling

```
uv run plain future enable [--branch <branch>]
```

- Defaults to the `future` branch. Use `--branch <name>` to test a specific feature branch (e.g. `forms-rebuild`).
- Rewrites `pyproject.toml` to add `[tool.uv.sources]` entries for all installed plain packages, then runs `uv sync`.
- The project is now on the future channel — expect breaking changes between syncs.

## Upgrading (pull latest + apply changes)

```
uv run plain future upgrade
```

This is the main workflow. It:

1. Runs `uv sync --upgrade-package <pkg>` for each tracked plain package.
2. Diffs the old/new commit SHAs from `uv.lock`.
3. Fetches each updated package's `FUTURE.md` from github and prints it.

Your job after running it:

1. Read each printed `FUTURE.md` — the **Upgrade instructions** section lists code changes the user needs to make.
2. Apply those changes to the user's code (renames, settings, imports, etc.).
3. Run `uv run plain agent install` to sync any updated rules and skills from the upgraded packages.
4. Run `uv run plain fix` then `uv run plain check` to validate.

## Disabling

```
uv run plain future disable
```

Removes the future-channel `[tool.uv.sources]` entries and re-runs `uv sync`. The project is back on stable PyPI releases.

## Guidelines

- The `enable` command edits `pyproject.toml`. The user should commit or revert the change deliberately — don't auto-commit.
- DO NOT commit code-change diffs from `upgrade` on the user's behalf — let them review.
- If the printed FUTURE.md is empty or shows "No FUTURE.md at this commit", that package may have graduated to stable — point the user at its `CHANGELOG.md` instead.
- Keep code changes minimal — only what the upgrade instructions explicitly require.
- Report any issues, conflicts, or ambiguous instructions back to the user.
