---
name: plain-upgrade
description: Upgrades Plain packages and applies required migration changes. Use when updating to newer package versions.
---

# Upgrade Plain Packages

## 1. Run the upgrade

```
uv run plain upgrade [package-names...]
```

This will show which packages were upgraded (e.g., `plain-models: 0.1.0 -> 0.2.0`).

## 2. Apply code changes for each upgraded package

For each package that was upgraded:

1. Run `uv run plain changelog <package> --from <old-version> --to <new-version>`
2. Read the "Upgrade instructions" section
3. If it says "No changes required", skip to next package
4. Apply any required code changes

## 3. Validate

1. Run `uv run plain fix` to fix formatting
2. Run `uv run plain preflight` to validate configuration

## Guidelines

- Process ALL packages before testing
- DO NOT commit any changes
- Keep code changes minimal and focused
- Report any issues or conflicts encountered
