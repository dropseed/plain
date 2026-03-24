---
name: plain-postgres-diagnose
description: Run Postgres health checks and fix issues. Use when asked to check database health, optimize the database, find unused indexes, or diagnose Postgres problems.
---

# Database Diagnostics

Run health checks against the production Postgres database and act on findings locally.

## 1. Determine how to run the command

The diagnose command should run against the **production database**, not the local dev database. Ask the user how they run commands in production if you don't know. Common patterns:

- **Heroku**: `heroku run uv run plain db diagnose --json -a app-name`
- **Direct**: `uv run plain db diagnose --json` (if DATABASE_URL points to production)
- **Other platforms**: wrap with the platform's run command

For local/dev analysis, run directly:

```
uv run plain db diagnose --json
```

## 2. Interpret the JSON output

The output has two sections:

**`checks`** — an array of health check results, each with:

- `name` — check identifier
- `status` — `ok`, `warning`, `critical`, `skipped`, or `error`
- `items` — specific findings, each with:
    - `table`, `name`, `detail` — what was found
    - `source` — `"app"` (user's code), `"package"` (framework/third-party dependency), or `""` (unmanaged)
    - `package` — the package label (e.g., `"jobs"`, `"observer"`) if source is `"package"`
    - `suggestion` — what to do about it
- `message` — additional context

**`context`** — supporting information:

- `tables` — all tables with row counts, sizes, index counts, `source`, and `package`
- `connections` — active vs max connections
- `stats_reset` — when pg_stat_user_indexes was last reset (affects "unused" interpretation)
- `pg_stat_statements` — whether query analysis is available
- `slow_queries` — top 10 queries by total execution time (if available)

## 3. Fix issues

Get the JSON results from production, then make fixes locally in the codebase.

Process checks in priority order: critical first, then warnings.

**App items** (`source: "app"`): The user's own code. Fully actionable:

- Unused/duplicate indexes → find the index in the model's constraints, remove it, run `uv run plain makemigrations`
- Missing FK indexes → add an Index to the model, run `uv run plain makemigrations`

**Package items** (`source: "package"`): Owned by a framework or third-party package. Present these to the user with context:

- **Duplicate indexes** on package tables are likely framework bugs — mention them so the user is aware, and suggest reporting upstream
- **Unused indexes** on package tables may support features the app hasn't activated yet — these are not necessarily problems. Note them but don't recommend removal

**Unmanaged items** (`source: ""`): Tables not owned by any Plain model. Use direct SQL:

- Run the `suggestion` SQL directly (the command provides exact DDL)

**Operational issues** (sequence exhaustion, XID wraparound, vacuum health):

- These require direct database operations regardless of source
- For sequence exhaustion, alter the column type and create a migration
- For XID wraparound, investigate autovacuum configuration
- For vacuum health, check if autovacuum is keeping up

## 4. Re-run to verify

After deploying changes, run the diagnose command again on production to confirm the issues are resolved.
