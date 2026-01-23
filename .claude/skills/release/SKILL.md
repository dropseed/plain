---
name: release
description: Releases Plain packages with intelligent version suggestions and parallel release notes generation. Use when releasing packages to PyPI.
---

# Release Packages

Release Plain packages with version bumping, changelog generation, and git tagging.

## Arguments

```
/release [packages...] [--minor|--patch] [--force] [--no-verify]
```

- No args: discover all packages with changes, prompt for each
- Package names: only release specified packages
- `--minor`: auto-select minor release for all packages with changes
- `--patch`: auto-select patch release for all packages with changes
- `--force`: ignore dirty git status
- `--no-verify`: skip pre-commit checks

## Workflow

### Phase 1: Check Preconditions

1. Check git status is clean (unless `--force`):

    ```
    git status --porcelain
    ```

    If not clean, stop and ask user to commit or stash changes.

2. Run pre-commit checks (unless `--no-verify`):
    ```
    ./scripts/pre-commit
    ```

### Phase 2: Discover Packages with Changes

Run the discover-changes script to find packages with unreleased changes:

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

For each package to release (using `current_version` from discover-changes output):

```
cd <path> && uv version --bump <minor|patch>
```

Display the version change (e.g., "plain-code: 0.19.0 → 0.20.0").

### Phase 5: Generate Release Notes in Parallel

**IMPORTANT**: Use the Task tool to spawn one agent per package for parallel release notes generation.

For each package to release, spawn a Task agent with this prompt (using values from the discover-changes output):

```
Generate release notes for <name> version <new_version>.

1. Get the actual file changes since the last release:
   git diff <last_tag>..HEAD -- <name> ":(exclude)<name>/tests"

2. Read the diff output carefully to understand what actually changed.

3. Write release notes to <changelog_path>, prepending to the existing content.

Format:

## [<new_version>](https://github.com/dropseed/plain/releases/<name>@<new_version>) (<today's date>)

### What's changed

- Summarize user-facing changes based on the actual diff (not just commit messages)
- Include commit hash links: ([abc1234](https://github.com/dropseed/plain/commit/abc1234))
- Skip test changes, internal refactors that don't affect public API

### Upgrade instructions

- Specific steps if any API changed
- If no changes required: "- No changes required."
```

Wait for all agents to complete.

### Phase 6: Format and Sync

Run once after all changes:

```
uv sync
./scripts/fix
```

### Phase 7: Commit Each Package

For each package to release:

```
git add <package>/pyproject.toml <package>/**/CHANGELOG.md
git add-hunks uv.lock --grep "<package-with-dot>" --context
git commit -m "Release <package> <version>" -n
git tag -a "<package>@<version>" -m "Release <package> <version>"
```

Note: `<package-with-dot>` uses dot notation (e.g., "plain.dev" for plain-dev).

### Phase 8: Push

Ask user if they want to push all changes:

```
git push --follow-tags
```

## Release Type Guidelines

Since all packages are pre-1.0, use:

- **Minor (0.x.0)**: New features, breaking changes, new APIs, significant additions
- **Patch (0.0.x)**: Bugfixes, minor tweaks, documentation, refactors

Analyze commit messages for keywords:

- Minor indicators: "add", "new", "feature", "breaking", "remove", "rename API"
- Patch indicators: "fix", "bugfix", "typo", "docs", "refactor", "update"
