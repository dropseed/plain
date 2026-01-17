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

For each package directory (directories starting with `plain` that are not `.egg-info`):

1. Find the last commit that changed the version in `<package>/pyproject.toml`:

    ```
    git log --format="%H" -- <package>/pyproject.toml
    ```

    For each commit, check if it actually changed the version line using `git show`.

2. Get commits since the last version change (excluding tests):

    ```
    git log --format="%H %s" <last_version_commit>..HEAD -- <package> ":(exclude)<package>/tests"
    ```

3. If no commits, skip this package.

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

For each package to release:

1. Get current version:

    ```
    uv version --short
    ```

    (run in package directory)

2. Bump version:

    ```
    uv version --bump <minor|patch>
    ```

    (run in package directory)

3. Get new version and display the change

### Phase 5: Generate Release Notes in Parallel

**IMPORTANT**: Use the Task tool to spawn one agent per package for parallel release notes generation.

For each package to release, spawn a Task agent with this prompt:

```
Generate release notes for <package> version <new_version>.

Find the previous release by looking at git tags matching "<package>@*" and get the most recent one.

Analyze all commits between the previous version tag and HEAD for this package directory.

Write release notes to the CHANGELOG.md file in the package (e.g., plain-admin/plain/admin/CHANGELOG.md).

The release notes should include:

## [<version>](https://github.com/dropseed/plain/releases/<package>@<version>) (<date>)

### What's changed

- Short summaries of changes an end-user would care about
- Include git commit hash links: ([abc1234](https://github.com/dropseed/plain/commit/abc1234))
- Skip internal refactors that don't affect public API

### Upgrade instructions

- Specific, actionable steps for upgrading from the previous version
- If no changes required, write: "- No changes required."

DO NOT include changes from other packages unless directly relevant.
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

1. Show the diff of pyproject.toml and CHANGELOG.md:

    ```
    git diff --color=always <package>/pyproject.toml <package>/**/CHANGELOG.md
    ```

2. Ask user to confirm commit

3. If confirmed:
    ```
    git add <package>/pyproject.toml <package>/**/CHANGELOG.md uv.lock
    git commit -m "Release <package> <version>" -n
    git tag -a "<package>@<version>" -m "Release <package> <version>"
    ```

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
