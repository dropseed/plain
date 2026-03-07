# Proposals

Implementation ideas for Plain packages. Check here before starting significant work — there may already be a proposal.

## Frontmatter

Every proposal should have YAML frontmatter:

```yaml
---
packages:
- plain.server
depends_on:
- server-architecture-review
related:
- plain-server-performance
---
```

- `packages` (required): what this touches. Use `plain-models`, `plain-jobs`, etc. for packages. Use dotted names for plain core submodules: `plain.server`, `plain.views`, `plain.http`, `plain.preflight`, `plain.assets`, `plain.runtime`, `plain.signals`, `plain.signing`, `plain.urls`, `plain.agents`, `plain.logs`
- `depends_on` (optional): proposals that must be done before this one (filenames without `.md`)
- `related` (optional): thematically connected proposals with no ordering requirement

## CLI

- `scripts/proposals` — dependency tree grouped by package (default)
- `scripts/proposals list` — flat table sorted by updated date
- `scripts/proposals list -s <term>` — search by name/title
- `scripts/proposals show <name>` — details with deps, blocks, and related (partial match works)
- All commands accept `--json` for machine-readable output

## When working with proposals

- Before starting a feature, check if a proposal exists
- When creating a proposal, add frontmatter with `packages`, `depends_on`, and `related`
- When finishing a proposal, delete the file — git history preserves it
- When editing a proposal, update `depends_on` and `related` if new connections emerge
