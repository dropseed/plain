---
name: plain-install
description: Installs Plain packages and guides through setup steps. Use when adding new packages to a project.
---

# Install Plain Packages

## 1. Install the package(s)

```
uv run plain install <package-name> [additional-packages...]
```

## 2. Complete setup for each package

1. Run `uv run plain docs <package>` and read the installation instructions
2. If the docs indicate it's a dev tool, move it: `uv remove <package> && uv add <package> --dev`
3. Complete any code modifications from the installation instructions

## Guidelines

- DO NOT commit any changes
- Report back with:
    - Whether setup completed successfully
    - Any manual steps the user needs to complete
    - Any issues or errors encountered
