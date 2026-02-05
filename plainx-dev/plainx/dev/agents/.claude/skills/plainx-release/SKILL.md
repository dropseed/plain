---
name: plainx-release
description: Releases plainx packages with version suggestions, changelog generation, and git tagging. Use when releasing a package to PyPI.
---

# Release Package

Release a plainx package with version bumping, changelog generation, and git tagging.

## Arguments

```
/plainx-release [--major|--minor|--patch]
```

- No args: analyze commits and prompt for version type
- `--major`: auto-select major release
- `--minor`: auto-select minor release
- `--patch`: auto-select patch release

## Scripts

| Script             | Purpose                                             |
| ------------------ | --------------------------------------------------- |
| `get-package-info` | Get package metadata and commits since last release |

## Workflow

### Phase 1: Check Preconditions

1. Check git status is clean:

    ```
    git status --porcelain
    ```

    If not clean, stop and ask user to commit or stash changes.

### Phase 2: Get Package Info

```
uv run ./.claude/skills/plainx-release/get-package-info
```

This outputs JSON with:

- `name`: Package name from pyproject.toml
- `current_version`: Current version
- `changelog_path`: Path to CHANGELOG.md
- `last_tag`: Most recent git tag for this package
- `repo_url`: GitHub URL (extracted from pyproject.toml)
- `commits`: List of commits since last tag (excluding tests)

If no commits since last release, inform the user and stop.

### Phase 2b: First Release Detection

If `current_version` is `0.0.0`, this is the **first release**:

1. Inform the user: "This package has never been released (version 0.0.0)."
2. Ask what version to release:
    - **0.1.0** - First development release (recommended for most packages)
    - **1.0.0** - First stable release (if the package is already production-ready)
3. Skip to Phase 4 with the chosen version (use `uv version <version>` to set it directly)

### Phase 3: Collect Release Decision

1. Display the commits since last release
2. **Analyze commits and suggest release type**:
    - **Major**: breaking changes, major API redesigns, significant removals
    - **Minor**: new features, significant additions, new APIs
    - **Patch**: small bugfixes, minor tweaks, documentation updates, refactors
3. Ask user to confirm or adjust (major/minor/patch/skip)
    - If `--major`, `--minor`, or `--patch` was passed, auto-select that type
    - If user chooses to skip, stop

### Phase 4: Set Version

For first releases (from 0.0.0):

```
uv version <version>
```

Where `<version>` is the chosen version like `0.1.0` or `1.0.0`.

For subsequent releases:

```
uv version --bump <type>
```

Where `<type>` is `major`, `minor`, or `patch`.

### Phase 5: Generate Release Notes

1. Get the new version:

    ```
    uv version --short
    ```

2. Get the file changes since the last release:

    ```
    git diff <last_tag>..HEAD -- . ":(exclude)tests"
    ```

    If no `last_tag`, use the initial commit or recent history.

3. Read the existing `<changelog_path>` file.

4. Prepend a new release entry to the changelog.

**For first releases:**

```
## [<new_version>](<repo_url>/releases/v<new_version>) (<today's date>)

Initial release.

- Brief summary of what the package provides
- Key features or capabilities
```

**For subsequent releases:**

```
## [<new_version>](<repo_url>/releases/v<new_version>) (<today's date>)

### What's changed

- Summarize user-facing changes based on the actual diff (not just commit messages)
- Include commit hash links: ([abc1234](<repo_url>/commit/abc1234))
- Skip test changes, internal refactors that don't affect public API

### Upgrade instructions

- Specific steps if any API changed
- If no changes required: "- No changes required."
```

### Phase 6: Commit, Tag, and Push

Guide the user through these steps explicitly:

1. **Stage files**:

    ```
    git add pyproject.toml <changelog_path> uv.lock
    ```

2. **Show what will be committed**:

    ```
    git diff --cached --stat
    ```

3. **Create commit**:

    ```
    git commit -m "Release v<new_version>"
    ```

4. **Create tag**:

    ```
    git tag -a v<new_version> -m "Release v<new_version>"
    ```

5. **GitHub Workflow Setup (first release only)**:

    Check if `.github/workflows/release.yml` exists. If not, ask:

    > "No release workflow found. Would you like to set up GitHub Actions to publish to PyPI when you push a tag?"

    If yes, copy `.claude/skills/plainx-release/release-workflow.yml` to `.github/workflows/release.yml`, then amend the commit:

    ```
    git add .github/workflows/release.yml
    git commit --amend --no-edit
    git tag -fa v<new_version> -m "Release v<new_version>"
    ```

    Remind the user to configure PyPI trusted publishing after pushing:
    - Go to https://pypi.org/manage/account/publishing/
    - Add trusted publisher: GitHub owner, repo name, workflow "release.yml" (no environment needed)

6. **Push commit and tag**:
    ```
    git push && git push --tags
    ```

Ask user to confirm before each destructive step (commit, push).

### Phase 7: GitHub Release (Optional)

After pushing, wait for the GitHub workflow to publish to PyPI. Once published, ask the user if they want to create a GitHub release:

```
gh release create v<new_version> --notes "<changelog entry summary>"
```

Or to use the full changelog entry from the file, extract and pass it manually.

## Release Type Guidelines

Consider the current version when suggesting release types:

### Pre-1.0 packages (0.x.y)

Most packages stay pre-1.0 for a long time. For these packages:

- **Minor (0.x.0)**: New features, breaking changes, new APIs, significant additions
- **Patch (0.0.x)**: Bugfixes, minor tweaks, documentation, refactors
- **Major (1.0.0)**: Only suggest if the user explicitly wants to mark the package as stable/production-ready

### Post-1.0 packages (x.y.z where x >= 1)

Once a package has reached 1.0, follow semver strictly:

- **Major (x.0.0)**: Breaking changes, API removals, incompatible changes
- **Minor (x.y.0)**: New features, new APIs, backwards-compatible additions
- **Patch (x.y.z)**: Bugfixes, minor tweaks, documentation, refactors

### Commit message indicators

- Breaking/major indicators: "breaking", "remove", "rename API", "redesign", "incompatible"
- Feature/minor indicators: "add", "new", "feature", "implement"
- Fix/patch indicators: "fix", "bugfix", "typo", "docs", "refactor", "update"
