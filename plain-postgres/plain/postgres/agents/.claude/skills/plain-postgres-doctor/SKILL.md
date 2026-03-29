---
name: plain-postgres-doctor
description: Check overall database health — schema correctness and operational health. Use when asked to check the database, validate schema, optimize indexes, or diagnose Postgres problems.
---

# Database Doctor

Check database health by running schema and operational checks, then fix any issues found.

**All checks are read-only.** Fixes are local code changes. Never run database mutations (`migrations apply`, direct SQL) without explicit user approval.

## 1. Dev only or production too?

Always start by checking the dev database — that's where you are and where fixes get verified. Ask the user if they also want to check production. Production is where schema drift and operational health issues matter most, but dev databases drift too (manual SQL, reverted migrations, branch switches).

If checking production, figure out how the user runs commands there (check for Procfiles, Dockerfiles, deploy scripts, etc.) or ask them. Both `schema` and `diagnose` need to run against the target database.

## 2. Run checks

### Schema correctness

```
uv run plain postgres schema --json
```

Checks whether the actual database matches what the models expect — drift from failed deploys, manual DDL, partial migrations, or branch switches. Also reports unknown tables (tables in the DB with no corresponding model) which are often left over from uninstalled packages.

### Operational health

```
uv run plain postgres diagnose --json
```

Finds unused/duplicate/missing indexes, sequence exhaustion, cache hit ratios, vacuum health, and slow queries. Stats-based checks (unused indexes, cache hit ratios) are most meaningful against production with real traffic. Structural checks (duplicate indexes, missing FK indexes) are valid in any environment.

The JSON output includes `suggestion` fields for each finding. If findings are on unmanaged tables, check whether those tables should exist at all — `schema` will have already flagged them as unknown.

## 3. Fix issues

Make code and migration changes in the local codebase. For app-owned items, this is typically model changes + `uv run plain migrations make`. For unknown tables, present `uv run plain postgres drop-unknown-tables` to the user — it shows what will be dropped and asks for confirmation. Use `--yes` to skip the prompt if the user wants the agent to run it directly. For other unmanaged items, the suggestions include exact DDL — present these to the user for review, do not run SQL directly.

## 4. Verify

For **structural diagnose findings** (duplicate indexes, missing FK indexes): confirm the issue also appears in dev before fixing — you can't verify a fix if you never saw the problem. Run checks before and after the fix, then deploy and re-verify in production.

For **schema drift**: the drift is environment-specific (prod may have manual DDL that dev doesn't). Verify by confirming your fix makes `schema` pass cleanly in dev, then deploy and re-verify in production.

Stats-based findings (unused indexes, cache hit ratios) can only be verified in production after deploy.
