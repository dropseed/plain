---
name: future
description: Navigate and manage the future/ directory — view dependency graphs, filter by arc, find unblocked futures, and identify what to work on next. Use when deciding what to work on, exploring planned work, or checking dependencies between futures.
---

# Future

The `future/` directory is a knowledge graph of where Plain is headed.

## Structure

```
future/
  postgres-first-data-layer/
    ARC.md                            # vision + numbered sequence
    models-explicit-create-update.md
    ...
  real-time-server/
    ARC.md
    server-h2-websockets.md
    ...
```

- **Arc directories** — narrative groupings, the big stories of where Plain is headed
- **ARC.md** — each arc's vision and numbered sequence of futures
- **Future files** — each one describes a possible future state of the project

Every future must belong to an arc — no top-level orphan files. If a future doesn't fit an existing arc, create a new arc for it.

## Futures

Individual markdown files with optional YAML frontmatter:

```yaml
---
related:
  - server-performance
depends_on:
  - db-connection-pool
---

# Title

Content...
```

### Frontmatter fields

- `related` (optional): linked futures — conceptual connections (bidirectional)
- `depends_on` (optional): hard dependency — this future is blocked until the dependency is done. Mostly used for cross-arc blocks.

### Naming

- Don't prefix filenames with `plain-` — use `models-cursor-paginator.md` not `plain-models-cursor-paginator.md`
- `related` and `depends_on` reference filenames without `.md`

## Arcs

Arc membership is determined by directory. Each arc directory contains an `ARC.md` with:

1. **Vision** — what Plain looks like at the end of this arc
2. **Sequence** — checklist of linked futures in intended order (place near the top, right after the vision)

Format: `- [ ] [future-name](future-name.md)` — checked when done. The sequence is the editorial ordering — "this is the path we'd like to take." `depends_on` is for hard blocks that can't be reordered. Any deeper context (research, references, industry analysis) goes after the sequence.

Current arcs:

- `postgres-first-data-layer` — making the ORM truly postgres-native
- `migration-rethink` — flat timestamps, convergence, advisory locks
- `real-time-server` — HTTP/2, websockets, realtime, performance
- `production-hardening` — security, compliance, operational maturity
- `uncategorized` — futures that don't belong to a specific arc yet

## Scripts

Run via `.claude/skills/future/future <command>`:

| Command       | Purpose                                                 |
| ------------- | ------------------------------------------------------- |
| `next`        | Unblocked futures sorted by downstream impact (default) |
| `graph`       | Full dependency tree from roots to leaves               |
| `list`        | All futures with status (root/ready/blocked)            |
| `show <name>` | Details for one future (partial match ok)               |
| `arcs`        | List all arcs with futures in sequence order            |

All commands support `--json` for structured output.

### Filters

- `list --arc <term>` — filter by arc (e.g. `postgres`, `server`)
- `list --search <term>` — search titles and filenames

## Presenting results

**Always summarize command output for the user.** The raw terminal output is not visible to them. After running any script command, present the results in your own words using markdown — describe what the data shows, highlight key patterns (blocked items, cross-arc dependencies, what's next), and provide context. Don't just run a command and stop.

## Workflow

When the user asks about priorities or what to do next:

1. Run `arcs` to see the full picture — all arcs with futures in sequence order
2. Run `next` to see unblocked futures ranked by impact
3. Use `show <name>` to dive into a specific future's dependencies and context
4. Read the actual future file for the full content
5. Present a summary to the user — describe each arc, what's blocked and why, and what's actionable

When the user asks to start working on a future:

1. Run `show <name>` to check dependencies and status
2. Read the future file for full context
3. Read the arc's `ARC.md` for the broader vision
4. Read any `related` or `depends_on` futures that provide useful background
5. Proceed with implementation

When a future is completed:

1. Delete the future file
2. If the entire arc is complete (all futures done), delete the arc directory
3. Clean up `related` and `depends_on` references to deleted futures in other files
4. Update the arc list in this skill if an arc was removed

When creating a new future:

1. Place it in an arc directory — every future must belong to an arc. If no arc fits, create a new one.
2. Add it to the arc's `ARC.md` sequence in the right position
3. Add `related` to link conceptually connected futures
4. Add `depends_on` only for hard cross-arc blocks
