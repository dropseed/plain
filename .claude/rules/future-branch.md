---
paths:
  - "**/FUTURE.md"
---

# Future Branch & FUTURE.md

Plain ships a `future` channel — a rolling unstable release stream that users opt into via `plain future enable`. Each package on the `future` branch accumulates user-facing changes in a `<pkg>/FUTURE.md` file (next to `CHANGELOG.md`). At release time, FUTURE.md content is consolidated into CHANGELOG.md and the file is deleted.

## Authoring rules

- **`FUTURE.md` only exists on the `future` branch.** Never commit it to `master`. If you see one on master, that's a missed graduation step.
- **Update `<pkg>/FUTURE.md` alongside any user-facing code change** when working on the `future` branch — same PR, same commit. The branch's value depends on FUTURE.md staying current.
- **Internal refactors and bug fixes don't need FUTURE.md entries** — same rule as deciding whether something is changelog-worthy.

## Format

Mirror an existing CHANGELOG.md entry exactly — no new schema:

```markdown
# plain — future

### What's changed

- **Trailing slash flipped to per-route.** New `URLS_TRAILING_SLASH` setting...
- ...

### Upgrade instructions

- Add `URLS_TRAILING_SLASH = True` to `app/settings.py`...
- ...
```

- `# <package-name> — future` h1
- `### What's changed` — bulleted, bold lead phrase per item, link commits where useful
- `### Upgrade instructions` — bulleted, imperative, what the user needs to do

If a change requires no user action, still list it under "What's changed" and write `- No changes required.` under upgrade instructions if the section would otherwise be empty.

## Why a separate file (vs. `## [Unreleased]` in CHANGELOG.md)

The `future` branch is long-lived and bidirectionally merged with `master`. Putting unreleased content in CHANGELOG.md creates recurring merge conflicts at the top of the file (stable releases land on master while future accumulates content). FUTURE.md lives only on the future branch, so master→future merges never touch it. Cleanup on graduation is also discrete (delete the file) rather than rename-a-section.

## Graduation

When `future` graduates, the `/release` skill consolidates each package's FUTURE.md into a new `## [VERSION]` block in CHANGELOG.md and deletes FUTURE.md. Stable users see the exact same release notes they would have seen otherwise.
