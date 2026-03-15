---
name: work
description: Navigate and manage the work/ directory — view dependency graphs, find unblocked explorations, search by label, and identify what to work on next.
---

# Work Tracker

The `work/` directory is lightweight file-based planning. Two structures:

- **`TODO.md`** — Ordered work queue. Markdown checklist, line order = priority.
- **`*.md` files** — Explorations. Research, future-state thinking, knowledge base.

## Explorations

Individual markdown files with YAML frontmatter:

```yaml
---
labels:
  - plain-models
related:
  - server-performance
depends_on:
  - db-connection-pool
---

# Title

Content...
```

### Frontmatter fields

- `labels` (required): what this touches. Use `plain-models`, `plain-jobs`, etc. for packages. Use dotted names for core modules: `plain.server`, `plain.views`, `plain.http`, etc.
- `related` (optional): linked explorations — conceptual connections (bidirectional)
- `depends_on` (optional): this thinking builds on that thinking. Creates a dependency graph.

### Naming

- Don't prefix filenames with `plain-` — use `models-cursor-paginator.md` not `plain-models-cursor-paginator.md`
- `related` and `depends_on` reference filenames without `.md`

## TODO.md

The work queue. A markdown checklist:

```markdown
- [ ] [DB connection pooling](db-connection-pool.md) — replace per-thread connections
- [ ] Fix broken worker recycling
```

- Simple tasks are just a line of text
- Complex tasks link to an exploration file for context
- Line order is priority — first unchecked item is next
- Check off when done: `- [x]`

## Dependency graph

The `depends_on` field creates a DAG:

- **Roots** (no `depends_on`): logical starting points
- **Dependents**: unlocked when their dependency is completed (file deleted)
- **Chains**: `db-connection-pool → models-psycopg3-features → ...`

## Lifecycle

1. An idea starts as an **exploration file** — research, thinking, sharpened over time
2. When ready to implement, add a line to **TODO.md** (linking to the exploration if complex)
3. Work through TODO.md in order
4. Check off completed items, delete the exploration file when done
5. Git history preserves everything

## Scripts

Run via `.claude/skills/work/work <command>`:

| Command       | Purpose                                                      |
| ------------- | ------------------------------------------------------------ |
| `next`        | Unblocked explorations sorted by downstream impact (default) |
| `graph`       | Full dependency tree from roots to leaves                    |
| `list`        | All explorations with status (root/ready/blocked)            |
| `show <name>` | Details for one exploration (partial match ok)               |

All commands support `--json` for structured output.

### Filters

- `list --label <term>` — filter by label (e.g. `plain-jobs`, `plain.server`)
- `list --search <term>` — search titles and filenames

## Workflow

When the user asks about work priorities or what to do next:

1. Run `next` to see unblocked explorations ranked by impact
2. Use `show <name>` to dive into a specific exploration's dependencies and context
3. Read the actual `work/<name>.md` file for the full exploration content
4. Check `work/TODO.md` for the ordered work queue

When the user asks to start working on an exploration:

1. Run `show <name>` to check dependencies and status
2. Read `work/<name>.md` for full context
3. Read any `related` or `depends_on` explorations that provide useful background
4. Proceed with implementation

When creating a new exploration:

1. Add `labels` to connect it to packages/modules
2. Add `related` to link conceptually connected explorations
3. Add `depends_on` if this work builds on another exploration
