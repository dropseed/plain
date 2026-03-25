# Postgres insights

Built-in Postgres diagnostics, health checks, and optimization tools — leveraging Plain's unique position of owning the full stack (ORM, migrations, models, admin, observer).

Unlike rails-pg-extras or pgHero, Plain can connect Postgres catalog stats back to application code: model-aware index suggestions, migration-integrated fixes, deploy marker correlation, and observer + system-level stat fusion.

## Sequence

- [x] [diagnose-command](diagnose-command.md)
- [x] [preflight-index-checks](preflight-index-checks.md)
- [x] [agent-skill](agent-skill.md)
- [ ] [fk-remove-auto-index](fk-remove-auto-index.md)

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

### What's unique to Plain's position

- **Model-aware index suggestions**: Not just "this table has high seq scans" but "your `PullRequest.query.filter(organization_id=X)` pattern would benefit from an index on `organization_id`" — connecting Postgres stats back to application code.
- **Migration-integrated fixes**: Suggest an index → generate the migration → apply it. pgHero's `autoindex` does raw DDL; Plain can do it through the migration system.
- **Deploy marker correlation**: Plain knows when migrations ran. Overlay that on query performance trends to catch regressions.
- **Observer + Postgres insights**: Observer captures per-request query traces. Postgres insights show system-level stats. Connecting them ("this N+1 query pattern accounts for 40% of seq scans on this table") is something no standalone tool can do.

### Implementation references

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
