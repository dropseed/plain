---
name: release
description: Releases Plain packages with intelligent version suggestions and parallel release notes generation. Use when releasing packages to PyPI.
---

# Release Packages

Release Plain packages with version bumping, changelog generation, and git tagging.

## Arguments

```
/release [packages...] [--minor|--patch] [--force]
```

- No args: discover all packages with changes, prompt for each
- Package names: only release specified packages
- `--minor`: auto-select minor release for all packages with changes
- `--patch`: auto-select patch release for all packages with changes
- `--force`: ignore dirty git status

## Scripts

All mechanical operations are handled by scripts in this skill directory:

| Script             | Purpose                                                         |
| ------------------ | --------------------------------------------------------------- |
| `discover-changes` | Find packages with unreleased commits (outputs JSON)            |
| `bump-versions`    | Bump package versions (`<package>:<type> ...`)                  |
| `commit-and-push`  | Format, sync, commit, tag, and push (`<package>:<version> ...`) |
| `add-hunks`        | Stage specific uv.lock hunks by grep pattern (used internally)  |

## Workflow

### Phase 1: Check Preconditions

1. Check git status is clean (unless `--force`):

    ```
    git status --porcelain
    ```

    If not clean, stop and ask user to commit or stash changes.

### Phase 2: Discover Packages with Changes

```
./.claude/skills/release/discover-changes
```

This outputs JSON with each package's name, current version, and commits since last release.
If specific packages were requested, filter the results to only those packages.

### Phase 3: Collect Release Decisions

For each package with changes:

1. Display the commits since last version change
2. **Analyze commits and suggest release type**:
    - **Minor**: new features, breaking changes, significant additions, new APIs
    - **Patch**: small bugfixes, minor tweaks, documentation updates, refactors
3. Ask user to confirm or adjust (minor/patch/skip)
    - If `--minor` or `--patch` was passed, auto-select that type
    - Default to skip if user just presses Enter

### Phase 4: Bump Versions

```
./.claude/skills/release/bump-versions <package>:<type> [<package>:<type> ...]
```

Example: `./.claude/skills/release/bump-versions plain-admin:patch plain-dev:minor`

### Phase 5: Generate Release Notes

For each package to release, sequentially:

1. Get the file changes since the last release:

    ```
    git diff <last_tag>..HEAD -- <name> ":(exclude)<name>/tests"
    ```

2. Read the existing `<changelog_path>` file.

3. Prepend a new release entry to the changelog with this format:

```
## [<new_version>](https://github.com/dropseed/plain/releases/<name>@<new_version>) (<today's date>)

### What's changed

- Summarize user-facing changes based on the actual diff (not just commit messages)
- Include commit hash links: ([abc1234](https://github.com/dropseed/plain/commit/abc1234))
- Skip test changes, internal refactors that don't affect public API

### Upgrade instructions

- Specific steps if any API changed
- If no changes required: "- No changes required."
```

### Phase 6: Commit, Tag, and Push

```
./.claude/skills/release/commit-and-push <package>:<version> [<package>:<version> ...]
```

This script handles everything: `uv sync`, `./scripts/fix`, staging files, committing each package separately, tagging, and pushing. Sub-packages are committed first, core `plain` last.

Example: `./.claude/skills/release/commit-and-push plain-admin:0.65.1 plain:0.103.0`

## Release Type Guidelines

Since all packages are pre-1.0, use:

- **Minor (0.x.0)**: New features, breaking changes, new APIs, significant additions
- **Patch (0.0.x)**: Bugfixes, minor tweaks, documentation, refactors

Analyze commit messages for keywords:

- Minor indicators: "add", "new", "feature", "breaking", "remove", "rename API"
- Patch indicators: "fix", "bugfix", "typo", "docs", "refactor", "update"
