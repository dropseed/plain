---
name: release
description: Releases Plain packages with intelligent version suggestions and parallel release notes generation. Use when releasing packages to PyPI.
---

# Release Packages

Release Plain packages with version bumping, changelog generation, and git tagging.

## Arguments

- No args: discover all packages with changes, prompt for each
- Package names: only release specified packages
- The user may also specify a release type (major/minor/patch) to auto-select for all packages

## Scripts

All mechanical operations are handled by scripts in this skill directory:

| Script             | Purpose                                                         |
| ------------------ | --------------------------------------------------------------- |
| `discover-changes` | Find packages with unreleased commits (outputs JSON)            |
| `bump-versions`    | Bump package versions (`<package>:<type> ...`)                  |
| `commit-and-push`  | Format, sync, commit, tag, and push (`<package>:<version> ...`) |
| `add-hunks`        | Stage specific uv.lock hunks by grep pattern (used internally)  |

## Workflow

### Phase 1: Discover Packages with Changes

1. Run `git status --porcelain` to check for uncommitted changes.

2. Run discover-changes:

    ```
    ./.claude/skills/release/discover-changes
    ```

    This outputs JSON with each package's name, current version, and commits since last release.
    If specific packages were requested, filter the results to only those packages.

3. For each package that has changes to release, check if any of its files appear in the git status output. If so, **stop and warn the user** — uncommitted changes in a package being released could mean the release misses work or includes an inconsistent state. Ask them to commit or discard before proceeding. Changes in other directories (e.g. `work/`, `scripts/`) are fine to ignore.

### Phase 1b: First Release Detection

For any package with `current_version` of `0.0.0`:

1. Inform the user: "Package X has never been released (version 0.0.0)."
2. Ask what version to release:
    - **0.1.0** - First development release (recommended)
    - **1.0.0** - First stable release
3. Use `uv version <version>` in the package directory to set the version directly (instead of bump)

### Phase 2: Collect Release Decisions

For each package with changes:

1. Display the commits since last version change
2. **Analyze commits and suggest release type**:
    - **Minor**: new features, breaking changes, significant additions, new APIs
    - **Patch**: small bugfixes, minor tweaks, documentation updates, refactors
3. Ask user to confirm or adjust (minor/patch/skip)
    - If user specified a release type, auto-select that type
    - Default to skip if user just presses Enter

### Phase 3: Bump Versions

```
./.claude/skills/release/bump-versions <package>:<type> [<package>:<type> ...]
```

Example: `./.claude/skills/release/bump-versions plain-admin:patch plain-dev:minor`

### Phase 3b: Update Cross-Package Dependency Minimums

When a package is being released because it depends on changes in another package being released in the same batch, update its minimum version constraint in `pyproject.toml`.

For each sub-package being released, check if any of its dependencies (in `[project.dependencies]`) are also being released in this batch. If so, and the sub-package's changes are driven by the dependency's changes (e.g., adapting to a new API), update the constraint from `<1.0.0` to `>=<new_version>,<1.0.0`.

Example: if `plain-auth` is being released because it adapted to `plain` 0.113.0's new Request API, update its pyproject.toml:

- Before: `"plain<1.0.0"`
- After: `"plain>=0.113.0,<1.0.0"`

Only update constraints when there's an actual compatibility requirement — don't add minimums for packages whose changes are independent. Use the commit analysis from Phase 3 to determine this.

### Phase 4: Generate Release Notes

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

### Phase 5: Commit, Tag, and Push

```
./.claude/skills/release/commit-and-push <package>:<version> [<package>:<version> ...]
```

This script handles everything: `uv sync`, `./scripts/fix`, staging files, committing each package separately, tagging, and pushing. Sub-packages are committed first, core `plain` last.

Example: `./.claude/skills/release/commit-and-push plain-admin:0.65.1 plain:0.103.0`

## Release Type Guidelines

Consider the current version when suggesting release types:

### Pre-1.0 packages (0.x.y)

Most Plain packages are pre-1.0. For these:

- **Minor (0.x.0)**: New features, breaking changes, new APIs, significant additions
- **Patch (0.0.x)**: Bugfixes, minor tweaks, documentation, refactors
- **Major (1.0.0)**: Only suggest if explicitly requested for stability milestone

### Post-1.0 packages (x.y.z where x >= 1)

Follow semver strictly:

- **Major (x.0.0)**: Breaking changes, API removals, incompatible changes
- **Minor (x.y.0)**: New features, new APIs, backwards-compatible additions
- **Patch (x.y.z)**: Bugfixes, minor tweaks, documentation, refactors

### Commit message indicators

- Breaking/major indicators: "breaking", "remove", "rename API", "redesign", "incompatible"
- Feature/minor indicators: "add", "new", "feature", "implement"
- Fix/patch indicators: "fix", "bugfix", "typo", "docs", "refactor", "update"
