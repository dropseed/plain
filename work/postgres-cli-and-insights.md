---
labels:
  - plain-postgres
related:
  - db-schema-command
  - migrations-schema-check
  - models-index-suggestions
---

# postgres: CLI rename and Postgres insights

## Rename `plain db` → `plain postgres`

The framework is Postgres-only. `plain db` is a generic name inherited from Django's multi-backend world. Rename to `plain postgres` — existing commands (`shell`, `wait`, `drop-unknown-tables`, `backups`) move under it.

This also creates a natural namespace for Postgres-specific insight commands that wouldn't make sense under a generic `db` prefix.

## Industry context

Everyone builds the same thing on top of the same Postgres system catalogs. The SQL queries are well-known and shared across implementations — the differentiation is in presentation and integration.

### Existing tools

**rails-pg-extras** (35+ queries): The most comprehensive CLI query library. Includes a `diagnose` command that runs 12 checks with configurable thresholds (cache hit ≥98.5%, unused indexes >1MB with <20 scans, bloat ≥10x, etc.). Also has a mountable web UI and programmatic Ruby API. Detects missing FK indexes and missing FK constraints — unique among these tools.

**pgHero** (web dashboard + API): The most feature-rich overall. Unique capabilities: suggested indexes via SQL parsing + `pg_stats` column statistics, auto-index creation, historical query/space stats captured on a schedule and charted over time, cloud provider metrics (AWS RDS, GCP, Azure), EXPLAIN visualization, sequence exhaustion warnings (>90% capacity), TX ID wraparound detection. Color-coded dashboard with green/yellow/red health indicators.

**Heroku pg:extras/pg:diagnose**: CLI-only. `pg:diagnose` runs 14 checks server-side with red/yellow/green results. Includes TX ID wraparound and sequence exhaustion checks. Tightly coupled to Heroku platform.

**Crunchy Bridge Insights**: 14 diagnostic queries available via `cb psql :menu`. Includes a Production Check feature — automated preflight checks for HA, connection pooling, statement_timeout, pg_stat_statements, integer PK overflow detection. Recommends specific thresholds: cache hit ~99%, index hit 99%+, idle connections warning >20, total connections warning >40.

**PlanetScale Insights**: The most sophisticated analysis layer. Key innovations:

- **Rows read/returned ratio** as a core efficiency metric — high ratio = missing index. Computable from `pg_stat_statements`.
- **Per-query statistical anomaly detection** — baselines each query pattern's mean+stddev over a week, flags when >2σ above normal. Avoids false positives from inherently slow queries.
- **Pearson correlation** to identify root-cause queries during anomalies.
- **HypoPG** for validating index suggestions — creates hypothetical indexes the Postgres planner evaluates without materializing them.
- **Deploy markers on performance graphs** — correlate migration timestamps with query performance changes.
- **Query tagging via sqlcommenter** — annotate SQL with application context (view, user) for error/performance filtering.

**PlanetScale database-skills** (database-skills.com): AI agent skills (structured markdown) installable into coding assistants. Ships diagnostic SQL queries, optimization checklists, schema design rules, and quantitative thresholds (e.g., index count <5 normal, 5-10 review, >10 audit). Interesting model — Plain already has a similar concept with its agents/skills system.

### Common high-value checks across all tools

Every tool implements these — they're the universal "worth checking" set:

| Check                | Source view                    | Threshold                       |
| -------------------- | ------------------------------ | ------------------------------- |
| Cache hit ratio      | `pg_statio_user_tables`        | ≥99%                            |
| Index hit ratio      | `pg_statio_user_indexes`       | ≥99%                            |
| Unused indexes       | `pg_stat_user_indexes`         | <50 scans, >1MB                 |
| Duplicate indexes    | `pg_index`, `pg_attribute`     | any                             |
| Missing indexes      | `pg_stat_user_tables`          | seq_scan >> idx_scan, >10k rows |
| Table/index bloat    | `pg_stat_user_tables`          | ≥10x ratio                      |
| Long-running queries | `pg_stat_activity`             | >1 min                          |
| Lock contention      | `pg_locks`, `pg_stat_activity` | blocking present                |
| Connection count     | `pg_stat_activity`             | near limit                      |
| Sequence exhaustion  | `pg_sequences`                 | >90% of type max                |
| TX ID wraparound     | `pg_database`                  | <10M remaining                  |
| Vacuum health        | `pg_stat_user_tables`          | dead tuples, last vacuum age    |

## What Plain should build

### 1. `plain postgres diagnose` — the headline command

A single command that runs the high-value checks above and gives pass/fail results. This is the pattern every tool converges on (rails-pg-extras `diagnose`, Heroku `pg:diagnose`, Crunchy Bridge Production Check).

```
$ plain postgres diagnose

  Cache hit ratio          99.7%                  ✓
  Index hit ratio          99.9%                  ✓
  Unused indexes           2 (3.2 MB)             !  reviews_idx_old, tmp_migration_idx
  Duplicate indexes        none                   ✓
  Missing indexes          1 table                !  pullrequests_pullrequest (92% seq scans)
  Bloat                    normal                 ✓
  Long-running queries     none                   ✓
  Connections              12 active, 3 idle      ✓
  Sequence exhaustion      all OK                 ✓
  Vacuum health            all OK                 ✓

  8 passed, 2 warnings
```

This is the highest-value thing to ship first. Each check is a single SQL query. The work is in choosing thresholds and formatting output.

### 2. Individual insight commands

For drilling into specific areas when `diagnose` flags something:

- `plain postgres tables` — sizes, row counts, bloat
- `plain postgres indexes` — usage stats, duplicates, unused
- `plain postgres connections` — by state, user, application
- `plain postgres queries` — long-running, locks, outliers (requires `pg_stat_statements`)
- `plain postgres schema <Model>` — column types, constraints, indexes (see `db-schema-command`)

### 3. Preflight integration

Promote the checks that indicate real problems to preflight warnings:

- Unused indexes (wasted write overhead)
- Duplicate indexes
- Sequence exhaustion (will cause hard failure)
- TX ID wraparound danger
- Schema drift (see `migrations-schema-check`)

These run during `plain check` / deploy. Operational checks (connections, locks, long queries) stay CLI-only — they're point-in-time diagnostics, not deploy gates.

### 4. Admin panel

Dashboard showing the `diagnose` results plus historical trends. pgHero's approach of capturing stats on a schedule and charting them is the right model — you want to see "is cache hit ratio trending down?" not just "what is it right now?"

### 5. AI agent skill

Following the database-skills.com model, ship a postgres optimization skill that gives the AI agent access to diagnostic queries, threshold knowledge, and optimization patterns. Plain already has the skill infrastructure — this would be a natural addition. The skill could run `diagnose`, interpret results, and suggest specific actions.

## What's unique to Plain's position

Unlike rails-pg-extras or pgHero, Plain owns the full stack: ORM, migrations, models, admin, observer, and now the Postgres insight layer. This enables things the standalone tools can't do:

- **Model-aware index suggestions**: Not just "this table has high seq scans" but "your `PullRequest.query.filter(organization_id=X)` pattern would benefit from an index on `organization_id`" — connecting Postgres stats back to application code.
- **Migration-integrated fixes**: Suggest an index → generate the migration → apply it. pgHero's `autoindex` does raw DDL; Plain can do it through the migration system.
- **Deploy marker correlation**: Plain knows when migrations ran. Overlay that on query performance trends to catch regressions.
- **Observer + Postgres insights**: Observer captures per-request query traces. Postgres insights show system-level stats. Connecting them ("this N+1 query pattern accounts for 40% of seq scans on this table") is something no standalone tool can do.

## Implementation references

**SQL queries to pull from:**

- [rails-pg-extras query definitions](https://github.com/pawurb/ruby-pg-extras/tree/master/lib/ruby-pg-extras/queries) — 35+ queries, each a standalone `.sql` file. Most directly reusable source.
- [pgHero methods](https://github.com/ankane/pghero/tree/master/lib/pghero) — modular Ruby, one file per feature area (indexes, queries, connections, space, maintenance, sequences, replication).
- [Crunchy Bridge diagnostic SQL examples](https://docs.crunchybridge.com/insights-metrics) — clean, commented queries with recommended thresholds.

**Index suggestion algorithm (pgHero):**

- Uses [`pg_query`](https://github.com/pganalyze/pg_query) to parse SQL and extract tables/WHERE/ORDER BY columns
- Queries `pg_stats` for null fractions, distinct value counts, row estimates to determine optimal column ordering in composite indexes
- Limits to 2-column composites, skips tables <500 rows or <30% additional filtering
- Source: [`lib/pghero/methods/suggested_indexes.rb`](https://github.com/ankane/pghero/blob/master/lib/pghero/methods/suggested_indexes.rb)

**HypoPG for index validation (PlanetScale approach):**

- [`hypopg`](https://github.com/HypoPG/hypopg) Postgres extension creates hypothetical indexes the planner evaluates without materializing
- PlanetScale uses LLM to suggest indexes, then validates via HypoPG `EXPLAIN` cost comparison
- Two-stage approach avoids both heuristic limitations and LLM hallucination risk

**Anomaly detection (PlanetScale approach):**

- Per-query-pattern baseline: mean + stddev of execution time over 7 days
- Anomaly threshold: >2σ above pattern's own mean (97.7th percentile)
- Root cause identification: Pearson correlation between each query pattern's rate and overall DB health during anomaly window
- Source: [PlanetScale anomalies blog post](https://planetscale.com/blog/introducing-insights-anomalies)

**Diagnose thresholds (rails-pg-extras):**

- All configurable via env vars (e.g., `PG_EXTRAS_TABLE_CACHE_HIT_MIN_EXPECTED`)
- Defaults: cache hit ≥0.985, unused index threshold <20 scans AND >1MB, bloat ≥10x, `random_page_cost` ≠ "4" (PG default is bad for SSDs), `work_mem` ≠ "4096 kB" (PG default is low)
- Source: [`lib/rails-pg-extras.rb` diagnose method](https://github.com/pawurb/rails-pg-extras/blob/master/lib/rails-pg-extras.rb)

**AI agent skill model (PlanetScale database-skills):**

- [github.com/planetscale/database-skills](https://github.com/planetscale/database-skills) — structured markdown skills for AI coding assistants
- Postgres skill has 22 reference docs covering schema design, indexing, optimization, MVCC, monitoring
- Includes quantitative thresholds (index count <5 normal, 5-10 review, >10 audit; leaf density <70% = bloat)
- Installed via `npx skills add` — Plain equivalent would be a package-level agent skill

## Open questions

- `plain postgres` or `plain pg` for brevity? Heroku uses `pg`, but `postgres` is more explicit.
- Should `diagnose` have `--json` output for CI pipelines?
- Which checks should have configurable thresholds vs. hardcoded sensible defaults?
- For the admin panel, capture stats on a schedule (like pgHero) or compute on-demand? Scheduled capture needs a background job; on-demand is simpler but no historical trends.
