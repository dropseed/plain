---
name: plain-upgrade
description: Upgrades Plain packages and applies required migration changes. Use when updating to newer package versions.
---

# Upgrade Plain Packages

## 1. Run the upgrade

```
uv run plain upgrade [package-names...]
```

This will show which packages were upgraded (e.g., `plain-postgres: 0.1.0 -> 0.2.0`).

## 2. Review the changelog for each upgraded package

For each package that was upgraded:

1. Run `uv run plain changelog <package> --from <old-version> --to <new-version>`
2. Read both sections:
    - **"What's changed"** — new features, behavior changes, bug fixes worth knowing about
    - **"Upgrade instructions"** — required code changes (or "No changes required")
3. If there are required code changes, apply them
4. Capture a short summary of "What's changed" for the final report — surface new APIs, new settings, new CLI commands, performance improvements, and notable bug fixes even when no code changes are required. Skip pure internal cleanup.

## 3. Update agent rules and skills

Run `uv run plain agent install` to sync any updated rules and skills from the upgraded packages.

## 4. Validate

1. Run `uv run plain fix` to fix formatting
2. Run `uv run plain check` to validate (linting, preflight, migrations, tests)

## 5. Report

For each upgraded package, report:

- Version bump (e.g., `plain-postgres: 0.103.0 -> 0.105.0`)
- A 1-3 bullet summary of notable changes from "What's changed" (new features, behavior changes, perf wins, notable fixes)
- What code changes were applied (or "no code changes required")

## Guidelines

- Process ALL packages before testing
- DO NOT commit any changes
- Keep code changes minimal and focused
- Report any issues or conflicts encountered
