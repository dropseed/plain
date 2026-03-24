---
related:
  - diagnose-command
---

# AI agent skill for Postgres optimization

Following the database-skills.com model, ship a postgres optimization skill that gives the AI agent access to diagnostic queries, threshold knowledge, and optimization patterns. Plain already has the skill infrastructure — this would be a natural addition.

The skill could run `diagnose`, interpret results, and suggest specific actions (create an index, rewrite a query, run REINDEX CONCURRENTLY, etc.).
