# Migration format and auto-detection

## Problem

Today's migration system generates migrations for model changes that don't affect the database at all:

| Change             | Migration? | Actual DDL? |
| ------------------ | ---------- | ----------- |
| `choices`          | Yes        | No          |
| `validators`       | Yes        | No          |
| `default` (non-db) | Yes        | No          |
| `on_delete`        | Yes        | No          |
| `related_name`     | Yes        | No          |
| `ordering`         | Yes        | No          |
| `required`         | Yes        | No          |
| `error_messages`   | Yes        | No          |

These exist to maintain "migration state" — a Python reconstruction of the model at each historical point. This state powers `apps.get_model()` in RunPython, which gives you a historical model with the right choices, validators, etc.

But the reconstructed model is a pale shadow: no custom methods, managers, or properties. Most developers are surprised when it doesn't work like the real model, and end up importing the actual class or using raw SQL anyway.

**Regardless of approach below, no-op migrations are eliminated.** Only DB-relevant changes produce migrations.

## Two approaches to auto-detection

Auto-detection is a core DX feature — you change the model, `makemigrations` figures out the DDL. The question is where the autodetector gets "current DB state" to diff against.

### Option A: DB introspection (no abstraction layer)

`makemigrations` connects to Postgres, introspects the actual schema, diffs against current models, generates SQL directly.

```sql
-- 20240315_110000_add_order_status.sql
ALTER TABLE orders ADD COLUMN status text NULL;
```

**How it works:**

1. `makemigrations` asks Postgres "what tables/columns do you have?"
2. Compares against what models declare
3. Generates DDL for the difference
4. Writes it to a `.sql` (or `.py` with SQL string) migration file

**Pros:**

- No abstraction layer at all — migration files are just SQL
- `postgres schema` already proves this diffing works
- Simpler codebase — no operation classes, no state replay, no ModelState/ProjectState
- What you see is what runs

**Cons:**

- Requires a running Postgres for `makemigrations`
- If your DB is out of sync (branch switching, manual changes), the diff could generate wrong DDL
- Rename detection is harder (was a column removed and another added, or was it renamed?)

**Mitigations for the cons:**

- In practice, when are you running `makemigrations` without a dev database? Basically never.
- `makemigrations` could refuse to generate if `postgres schema` shows existing drift — "your DB doesn't match existing migrations, run `postgres sync` first"
- Convergence keeps the DB in shape, reducing the "out of sync" risk
- Rename detection: prompt the developer ("did you rename `title` to `name`, or remove `title` and add `name`?") — same as today's autodetector, just without the heuristic

### Option B: Thin operations (no DB required)

`makemigrations` replays structured operations from existing migration files to compute "what the DB should look like," diffs against models, generates new operations.

```python
# 20240315_110000_add_order_status.py
class Migration:
    operations = [
        AddColumn("orders", "status", "text NULL"),
    ]
```

**How it works:**

1. Replay all existing migration operations in memory to build schema state
2. Compare schema state against current model definitions
3. Generate new operations for the difference
4. Each operation maps to exactly one DDL statement

**Pros:**

- No DB connection needed for `makemigrations`
- Deterministic — same models + same files = same output
- A broken DB can't corrupt migration generation

**Cons:**

- Needs a minimal abstraction layer (AddColumn, RemoveColumn, CreateTable, etc.)
- Must keep the in-memory replay logic in sync with what the operations actually do in SQL
- More framework code than Option A

**Either way, operations are much thinner than today** — just table name, column name, SQL type, nullability. No Field objects, no choices/validators/help_text tracking, no non_db_attrs.

## Initial direction: Option A (DB introspection)

Plain is Postgres-only and moving toward a "fully managed Postgres" future. The prerequisite is that your DB is in a known-good state — which is exactly what `postgres schema` enforces and convergence maintains.

This connects to a broader vision: **one comparison engine driving everything.** `postgres schema` already diffs models against the actual DB. That same engine powers:

- `postgres schema` — read-only: "here's what's different"
- `makemigrations` — generate SQL for the imperative parts of the diff (add/remove columns, tables)
- `postgres converge` — apply the declarative parts of the diff (indexes, constraints, NOT NULL)
- `postgres sync` — do all of the above in sequence

The prerequisite is that your DB matches the state of your existing migrations before you generate new ones. `makemigrations` should verify this (refuse to generate if drift is detected). This is reasonable — if your DB is out of sync, you should fix that first, not generate migrations from a broken baseline.

The payoff is significant: no abstraction layer, no state replay, no operation classes. Migration files can be plain SQL. The entire ModelState/ProjectState/operation machinery is eliminated — thousands of lines of the most complex code in the migration system.

_See updated direction below after industry research._

## RunPython uses current code

With no historical model reconstruction, data migrations import models directly and use the ORM:

```python
class Migration:
    def run(self, connection):
        from app.models import Order
        Order.query.filter(status=None).update(status="active")
```

Or raw SQL when the ORM doesn't fit:

```python
class Migration:
    def run(self, connection):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE orders SET status = 'active' WHERE status IS NULL")
```

The migration runs with Plain configured, same connection as the batch transaction. ORM operations are inside the transaction. It's the developer's responsibility to ensure data migrations work with the current codebase. Since old migrations get deleted (fresh DBs use model definitions), and data migrations are for one-time operations, this is practical.

## What this eliminates (either approach)

- No-op migrations for choices, validators, help_text, etc.
- `non_db_attrs` filtering in the schema editor
- `ModelState` / `ProjectState` / historical model reconstruction
- `apps.get_model()` in RunPython (use real imports instead)
- Full Field objects in migration files
- The entire "migration state" machinery

Option A additionally eliminates:

- Operation classes (AddField, RemoveField, etc.)
- State replay logic
- The schema editor's DDL generation indirection (operations → schema editor → SQL)

## Industry research

### Django — state replay, no DB required for generation

Django's autodetector compares two `ProjectState` objects: one built by replaying all existing migration operations in memory, the other constructed from current model classes. The diff produces operation objects (`AddField`, `RemoveField`, etc.) that both mutate state forward and generate DDL via the schema editor.

**No database needed for `makemigrations`.** The entire comparison is in-memory. This is Django's key architectural bet — and the source of its complexity.

**The cost is real and measurable.** In the Plain fork: `autodetector.py` (1,379 lines), `state.py` (882 lines), operation classes (1,528 lines across 4 files), `serializer.py` (378 lines), `writer.py` (302 lines), `loader.py` (377 lines), `graph.py` (364 lines). That's ~5,200 lines just for the state/replay/generation machinery, plus the schema editor (1,815 lines) that serves as the operation-to-DDL translation layer. In upstream Django, autodetector.py alone is 2,066 lines and state.py is 1,021 lines.

**Rename detection** uses heuristics — same field type on same model, one removed and one added — then prompts the developer interactively. The heuristic works because ModelState carries enough type information to make reasonable guesses.

**Known pain points:** No-op migrations for non-DB changes (choices, validators, etc.), model rendering performance issues (ticket #23745 required major optimization), huge memory load during unapplication (executor caches all intermediate ProjectStates), and the reconstructed historical models are "pale shadows" that surprise developers. The autodetector's `_detect_changes()` calls a dozen internal methods, some spanning hundreds of lines.

### Rails (ActiveRecord) — manual generation, DB-driven schema.rb

Rails does **not** auto-detect schema changes. `rails generate migration add_status_to_orders status:string` creates a migration file from the command line arguments. Developers write the migration DSL (`add_column`, `remove_column`, etc.) manually.

**schema.rb is generated by DB introspection**, not by replaying migrations. After any migration runs, Rails dumps the actual database state to `schema.rb`. This file is the authoritative schema representation — `db:schema:load` creates a fresh database from it, bypassing migration history entirely.

**No DB needed for migration creation** (because there's nothing to auto-detect — you're writing it yourself). DB is needed for `schema.rb` generation and for `db:migrate`.

**Key insight for Plain:** Rails proves that "migrations are deletable" works in practice. Old migrations become irrelevant once `schema.rb` exists. The schema file serves a "truth is in the model, not the history" role similar to Plain's convergence concept.

### Ecto (Elixir) — fully manual, no auto-detection

`mix ecto.gen.migration` creates an **empty** migration file. Developers write all schema changes manually using Ecto's migration DSL (`create table`, `add`, `alter`, `rename`).

**No auto-detection at all.** This is a deliberate design choice. The Ecto team rejected auto-detection in favor of explicit, developer-authored migrations. Ecto uses `structure.sql` (a `pg_dump` output) as the schema snapshot, similar to Rails' `schema.rb` but in raw SQL form.

**Advisory locks** (added in Ecto v3.9) prevent concurrent migration execution across multiple nodes. Migrations can be split into automatic (run during deploy) and manual (run post-deploy for long-running operations) directories.

**Key insight for Plain:** Ecto demonstrates that a successful migration system can work without auto-detection. But the DX tradeoff is real — developers must manually figure out and write the DDL for every model change. Plain's auto-detection is a DX advantage worth preserving.

### Laravel — manual generation, no auto-detection

Like Rails and Ecto, Laravel has **no auto-detection**. `php artisan make:migration` creates a migration file that developers populate manually using the Blueprint DSL (`$table->string('status')`, etc.).

**`schema:dump`** captures the current schema as a SQL file. Fresh databases load the dump then run only post-dump migrations. `--prune` deletes old migration files. This is the same "migrations are deletable" pattern as Rails.

**Key insight:** Three of the four major web frameworks (Rails, Laravel, Ecto) have fully manual migration authoring. Django is the outlier with auto-detection. This doesn't mean auto-detection is wrong — it's a significant DX advantage — but it contextualizes the complexity cost. Manual authoring is the industry default.

### Prisma — auto-detection, requires DB (shadow database)

Prisma auto-detects changes between the `schema.prisma` file and the migration history. The schema file is the single source of truth — a declarative DSL defining all models, fields, and relations.

**Requires a database.** `prisma migrate dev` uses a "shadow database" — a temporary database it creates and destroys on each run. The process:

1. Creates shadow database, replays all existing migration SQL files onto it
2. Introspects the shadow database to get "current state from history"
3. Compares against desired state from `schema.prisma`
4. Generates SQL migration file for the difference
5. Checks for schema drift (shadow state vs actual dev database)
6. Applies the migration to the dev database

**Rename detection does not exist.** Prisma cannot detect renames — it sees a drop + add and warns about data loss. Developers must use `--create-only` and manually edit the migration to use `ALTER ... RENAME`.

**`prisma migrate diff`** can generate SQL offline using `--from-empty --to-schema`, but the `--from-migrations` mode still requires a shadow database URL to replay history. Truly offline generation only works for "from scratch" scenarios.

**Key insight:** Prisma's shadow database approach is essentially Option A (DB introspection) combined with state replay — it replays migrations onto a temporary DB, then introspects it. This is the worst of both worlds complexity-wise: you need a DB _and_ you need to replay history. The reason is that Prisma's migration files are raw SQL (not replayable in memory), so it must use a real database to compute state from history.

### Atlas (Ariga) — the most relevant comparison

Atlas is the tool closest to what Option A proposes. It has two modes:

**Declarative mode** (`atlas schema apply`): Define desired state in HCL/SQL, Atlas diffs against live database, applies changes directly. No migration files at all. This is like a more sophisticated version of `postgres schema` + `converge`.

**Versioned Migration Authoring** (`atlas migrate diff`): The hybrid mode, and the most relevant to Plain. The process:

1. Define desired schema in HCL, SQL, or ORM schema files
2. Atlas replays existing migration directory onto a **dev database** to compute current state
3. Diffs current state against desired state
4. Generates a SQL migration file
5. Updates `atlas.sum` (integrity hash file)

**Requires a dev database** — specified via `--dev-url`, often a Docker-based ephemeral Postgres (`docker://postgres/15/dev`). The dev database is used to replay migrations and validate generated SQL. It's never the production or development database.

**Rename detection** (added in v0.22): Atlas detects potential renames and interactively prompts: "Did you rename column `first_name` to `name`? [Yes/No]". If yes, generates `ALTER ... RENAME`. If no, generates drop + add. The heuristic details aren't public, but the UX is the same as Django's approach.

**Migration files are pure SQL.** Reviewed in PRs like any other code. Atlas includes 50+ built-in analyzers that lint migrations for destructive changes, table locks, missing indexes, etc.

**Key insight:** Atlas proves that the "DB introspection + SQL migration files" approach works at scale. But critically, Atlas still replays the migration directory onto a dev DB to compute state — it doesn't introspect the developer's actual database. This avoids the "dirty dev DB" problem entirely. Atlas's dev database is always clean because it's ephemeral.

### Alembic (SQLAlchemy) — auto-detection, requires DB

`alembic revision --autogenerate` compares SQLAlchemy model metadata against the live database schema using `Inspector` methods (`get_table_names()`, `get_columns()`, etc.).

**Requires a database connection.** The comparison runs against the actual database, not a replayed state.

**Cannot detect renames.** Column and table renames appear as drop + add pairs. Developers must manually edit the generated migration. The documentation explicitly states: "autogenerate is not intended to be perfect — manual review is always required."

**Can detect:** table/column additions and removals, nullable changes, basic index and constraint changes, column type changes. **Cannot detect:** renames, anonymous constraints, enum types on some backends, CHECK constraints, sequences.

**Key insight:** Alembic is the closest existing tool to Option A's "introspect the actual DB" approach. Its main pain point is exactly what Option A would face: if the database is out of sync, the diff is wrong. Alembic has no mechanism to verify that the DB matches migration history first.

### EF Core (.NET) — auto-detection via model snapshot, no DB required

EF Core takes a unique approach: it maintains a `ModelSnapshot.cs` file — a C# code representation of the full model state. When you run `Add-Migration`:

1. Loads current model from `DbContext.OnModelCreating()`
2. Compares against `ModelSnapshot.cs` using `MigrationsModelDiffer`
3. Generates migration operations (AddColumn, CreateTable, etc.)
4. Updates the snapshot file

**No database connection needed.** The snapshot is pure code — a complete serialized representation of the model state.

**This is essentially Option B with a single snapshot file** instead of replaying all operations. The snapshot is updated with each migration, so there's no replay step. The tradeoff: the snapshot file itself becomes a merge conflict hotspot in team environments. Multiple developers creating migrations simultaneously will conflict on `ModelSnapshot.cs`.

**Key insight:** EF Core's snapshot approach is clever but fragile. It avoids the replay cost of Django's approach, but introduces merge conflict pain that Django avoids (since Django's state is distributed across individual migration files). The snapshot file for complex models gets very large.

### Flyway / Liquibase (Java) — manual, version-based

Both are **purely manual migration authoring** tools. No auto-detection.

**Flyway:** Versioned SQL files (`V01__Add_column.sql`). Linear version numbering. Simple, predictable. The Pro edition has experimental state-based diffing (compare DB to desired state, auto-generate SQL) but the docs warn against it for production due to non-deterministic SQL and data loss risks.

**Liquibase:** `diff-changelog` command can compare two databases and auto-generate a changelog. This is DB-to-DB comparison (requires two running databases), not model-to-DB. Useful for syncing environments but not for development workflow.

**Key insight:** Even in the Java ecosystem where these tools dominate, auto-detection is either absent or treated as a dangerous convenience. The rename problem is universal — Liquibase docs warn that "a renamed column may appear as a deletion and re-addition."

### golang-migrate / goose (Go) — manual, SQL files

Both are **fully manual** migration tools. `goose create <name> sql` generates an empty SQL file with `-- +goose Up` and `-- +goose Down` annotations. No auto-detection, no schema diffing.

**Atlas integration:** The Go ecosystem increasingly uses Atlas alongside goose — Atlas generates the SQL migration files, goose executes them. This separation of "planning" (Atlas) from "execution" (goose) is a clean architectural pattern.

### Sqitch — dependency-based, manual

Sqitch is notable for its **dependency graph** approach (like a Makefile or Git) rather than linear version numbering. Changes declare dependencies on other changes. Uses a Merkle tree for deployment integrity.

**Fully manual.** No auto-detection. Interesting for its dependency model, but not relevant to the generation question.

## Sharpened analysis

### The industry landscape

Auto-detection frameworks: **Django** (state replay, no DB), **Prisma** (shadow DB), **Atlas** (dev DB), **Alembic** (live DB introspection), **EF Core** (model snapshot). All five require either a database or a state-tracking abstraction layer. There is no free lunch.

Manual-only frameworks: **Rails**, **Laravel**, **Ecto**, **Flyway**, **Liquibase**, **goose**, **golang-migrate**, **Sqitch**. The majority of the industry lives here.

### Option A reassessed: "just introspect the DB"

The doc originally frames Option A as "introspect the developer's actual database." But the research reveals that **no successful tool does this as its primary approach.** Even Alembic, which introspects the live DB, acknowledges this is fragile and that manual review is always needed.

The tools that work well (Atlas, Prisma) introspect an **ephemeral database** they control:

- Atlas replays the migration directory onto a clean dev DB
- Prisma replays migrations onto a shadow database

Both still need a database, but they've solved the "dirty dev DB" problem by never using the developer's actual database for state computation.

**Plain's proposed approach is actually better than raw introspection** because `postgres schema` already provides a drift check. But the risk remains: if a developer has un-migrated manual changes in their dev DB, `makemigrations` will generate incorrect SQL. The mitigation ("refuse if drift detected") is sound but adds a mandatory verification step to every `makemigrations` run.

### Option B reassessed: "is the abstraction worth it?"

The complexity argument against Option B was "thousands of lines of code." The research clarifies this:

**What Option B actually requires (thin version):**

- ~8-10 operation classes: `CreateTable`, `DropTable`, `AddColumn`, `DropColumn`, `RenameColumn`, `RenameTable`, `AlterColumn`, `RunSQL`, `RunPython`
- Each operation is ~20-30 lines: store the args, emit one SQL statement, update an in-memory schema dict
- A schema state class: dict of `{table_name: {column_name: type_info}}` — maybe 100 lines
- Replay logic: iterate operations, call `state_forward()` on each — maybe 30 lines
- Total: ~500-700 lines of new code

**What it doesn't require (because convergence handles these):**

- No index operations, no constraint operations, no NOT NULL operations
- No dependency graph (flat timestamp list)
- No Field objects in operations (just table name, column name, SQL type string)
- No `ModelState` / `ProjectState` with app labels, relations, managers
- No model rendering, no stale pointer bugs, no memory bloat

The delta between Option A and Option B is not "thousands of lines" — it's roughly 500-700 lines of straightforward mapping code. The "thousands of lines" figure (accurate for Django) counts complexity that Plain eliminates regardless of which option is chosen.

### The rename detection problem is universal

Every tool handles renames the same way: they can't reliably auto-detect them, so they prompt the developer. Django heuristically guesses (same type, one removed + one added), Atlas prompts interactively, and everyone else (Prisma, Alembic, Flyway, Liquibase) simply can't detect renames at all.

**Option A and Option B are equivalent here.** Both see "column X disappeared, column Y appeared" and must ask the developer. Option B has a slight edge: the operation-level representation makes it trivial to emit `RenameColumn("orders", "title", "name")` which is unambiguous in code review. Option A generates `ALTER TABLE orders RENAME COLUMN title TO name` — equally readable as SQL.

### "Migration files are just SQL" — how much does it matter?

Prisma and Atlas both generate SQL migration files, and reviewers seem to find them perfectly readable. But the argument for SQL isn't about readability — it's about **eliminating the translation layer.** With SQL files, what's in the file is exactly what runs. No operation class interpreting intent and generating DDL through a schema editor.

However, thin operations also have this property: `AddColumn("orders", "status", "text NULL")` maps to exactly one `ALTER TABLE orders ADD COLUMN status text NULL`. The translation is trivial and mechanical — not the complex multi-step translation that Django's operation → schema editor → SQL chain involves.

The real readability advantage of pure SQL shows up in **complex migrations** — multi-statement operations, conditional DDL, custom Postgres features. For the common case (add/remove/rename column/table), thin operations and SQL are equally clear.

### "No DB needed" — how often does it matter?

Scenarios where DB-free migration generation helps:

- **CI checks:** "Are there pending model changes without a migration?" This check is trivial with Option B, requires spinning up Postgres with Option A.
- **Offline development:** Rare in practice (who develops DB-backed apps without a DB?), but possible.
- **Branch switching:** With Option A, switching branches may leave the DB in a state that doesn't match the new branch's models, requiring `postgres sync` before `makemigrations`. Option B is branch-agnostic.
- **Fresh clone:** A new contributor cloning the repo can run `makemigrations` to verify everything is in order without setting up Postgres first. Minor but reduces onboarding friction.

The CI check is the strongest argument. "Does the model match the migration state?" is a common CI gate. With Option A, this requires Postgres in CI (which most projects have anyway, but it's an additional dependency for the check). With Option B, it's a pure Python comparison.

## Option C: Hybrid (Atlas-style)

The research reveals a third approach used by Atlas and (partially) by Prisma:

**Declarative schema file + generated SQL migrations.**

The developer edits a schema-as-code file (in Plain's case, the models themselves serve this role). The tool diffs the desired state against the state computed from migration history, then generates a SQL migration file.

Plain already has the ingredients:

- **Desired state:** Model definitions (already exist)
- **Current state computation:** This is the key question — DB introspection (Option A) or file replay (Option B)
- **Migration output:** SQL files (either approach can produce these)

The hybrid insight is: **use a clean ephemeral database for state computation, not the developer's actual DB.** Atlas does this with its `--dev-url` (docker-based throwaway Postgres). Prisma does it with the shadow database.

This would mean:

1. `makemigrations` spins up (or connects to) a clean ephemeral Postgres
2. Replays existing migration SQL files onto it
3. Introspects the result to get "current state"
4. Diffs against model definitions
5. Generates SQL migration file

This gets the benefits of Option A (no abstraction layer, SQL output, single diff engine) while avoiding its main risk (dirty dev DB producing incorrect diffs). The cost: `makemigrations` requires Postgres, but uses a controlled instance, not the developer's potentially-drifted database.

**However, this is more complex than either pure option.** It requires Docker or a dedicated ephemeral DB setup. Atlas makes this seamless (`docker://postgres/15/dev`), but it's still infrastructure that must work reliably.

## Direction: Option A (DB introspection), with safeguards

The research reinforces Option A but with an important refinement: **the developer's database must be verified clean before diffing.**

The strongest argument for Option A:

1. **Plain already has the diff engine.** `postgres schema` introspects the DB and compares to models. Reusing this for `makemigrations` is straightforward — the hard work is done.
2. **Convergence keeps the DB clean.** Unlike Alembic (where the DB can drift silently), Plain's `postgres sync` / `converge` workflow actively maintains DB state.
3. **The abstraction layer savings are real but modest.** Option B's thin operations add ~500-700 lines, not thousands. But those 500-700 lines are 500-700 lines that must be kept perfectly in sync with what the SQL actually does — a maintenance surface that doesn't exist with Option A.
4. **Migration files as SQL is a genuine advantage** for the Postgres-first vision. Developers see exactly what DDL runs, can use any Postgres feature, and don't need to learn an operation API.

The strongest argument against Option A:

1. **CI migration checks require Postgres.** Solvable (most Plain projects already have Postgres in CI), but it's a dependency.
2. **Branch switching can dirty the DB.** Mitigated by the drift check and `postgres sync`, but adds friction.

**Refined approach:**

- `makemigrations` introspects the developer's actual DB (like `postgres schema` already does)
- Before diffing, it verifies the DB matches existing migration state (refuse with clear error if drift detected)
- Migration output is `.sql` for schema DDL, `.py` for `RunPython` data operations
- If the "spin up ephemeral DB" approach (Option C) proves simple enough to implement, it could be offered as `makemigrations --clean` for when the dev DB is in a bad state, but it shouldn't be the default workflow

The ephemeral DB approach (Option C) is worth keeping in mind as a fallback, but making it the default adds complexity (Docker dependency, startup latency) that doesn't match Plain's "simple by default" ethos. Introspecting the dev DB with a drift guard is simpler and sufficient for the vast majority of cases.

## Open questions (updated)

- **Resolved: `.sql` vs `.py` for migration files.** `.sql` for auto-generated schema DDL (the common case), `.py` for data operations (developer-written Python). File extension doubles as fresh-db discrimination: `.sql` = skip on empty DB (schema from models), `.py` = always run (data operations). Each `.sql` file contains a single DDL statement. Runner supports both formats plus legacy `.py`-with-operations for transition. See slim-migrations.md for full format specification.
- **Resolved: rename detection.** Interactive prompt, same as Django and Atlas. "Did you rename `title` to `name`?" The implementation is the same regardless of Option A vs B — the diff sees a column disappear and another appear with the same type.
- **Resolved: `makemigrations` safeguard.** Yes, always verify DB matches migration state first. This is a fast check (compare introspected column/table names against what migrations should have produced). Not a full schema comparison — just the imperative parts (tables and columns), not indexes/constraints (which convergence handles).
- **Partially resolved: package-shipped migrations.** Packages ship `.sql` files. SQL is universally portable and reviewable. A package's migration is just `ALTER TABLE` / `CREATE TABLE` SQL, same as any project migration.
- **Open: CI migration check without Postgres.** The `makemigrations --check` (verify no pending changes) workflow requires Postgres with Option A. Potential solutions: (a) require Postgres in CI (reasonable for a Postgres-first framework), (b) maintain a lightweight schema manifest file that can be checked without a DB (adds complexity but enables fast CI checks), (c) accept this as a tradeoff.
- **Open: ephemeral DB as escape hatch.** If implementing `makemigrations --clean` (spin up temporary Postgres, replay migrations, introspect clean state), how complex is this? Atlas makes it look easy with Docker URL syntax. Worth prototyping to see if the UX justifies the implementation cost.
