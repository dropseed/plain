# Proposals

Implementation ideas and roadmap for Plain packages. Check here before starting significant work — there may already be a proposal.

## Ordering

Numbered proposals are the active roadmap — work them in order:

```
001-db-connection-pool.md        ← do this first
002-models-rename-to-postgres.md ← then this
server-performance.md            ← backlog (no number)
```

- `001-`, `002-`, etc. — ordered queue of what's happening next
- No prefix — backlog, unordered ideas for later
- Delete when done — git history preserves it

When finishing a numbered proposal, delete it and don't renumber the rest. Gaps are fine.

## Frontmatter

```yaml
---
packages:
  - plain-models
related:
  - server-performance
---
```

- `packages` (required): what this touches. Use `plain-models`, `plain-jobs`, etc. for packages. Use dotted names for plain core submodules: `plain.server`, `plain.views`, `plain.http`, `plain.preflight`, `plain.assets`, `plain.runtime`, `plain.signals`, `plain.signing`, `plain.urls`, `plain.agents`, `plain.logs`
- `after` (optional): proposal that should be done before this one (filename without `.md`)
- `related` (optional): thematically connected proposals

## CLI

- `scripts/proposals` — list proposals grouped by package
- `scripts/proposals list` — flat table sorted by updated date
- `scripts/proposals list -s <term>` — search by name/title
- `scripts/proposals show <name>` — details (partial match works)
- All commands accept `--json` for machine-readable output

## Naming

- Don't prefix filenames with `plain-` — use `models-cursor-paginator.md` not `plain-models-cursor-paginator.md`
- `related` references other proposal filenames (without `.md`), not package names

## When working with proposals

- Before starting a feature, check if a proposal exists
- When creating a proposal, add frontmatter with `packages` and optionally `related`
- When finishing a proposal, delete the file
- To prioritize work, add a number prefix to move it into the ordered queue
