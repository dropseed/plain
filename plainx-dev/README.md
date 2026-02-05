# plainx-dev

Development tools for plainx package developers.

## Installation

Add as a dev dependency:

```bash
uv add --dev plainx-dev
```

## Skills

After installing, run `plain agent install` to copy skills to your `.claude/` directory.

### /plainx-release

A release workflow skill that helps you:

- Analyze commits and suggest version bump type (major/minor/patch)
- Generate release notes from actual code changes
- Update CHANGELOG.md
- Guide through commit, tag, and push steps

Usage:

```
/plainx-release
/plainx-release --major
/plainx-release --minor
/plainx-release --patch
```
