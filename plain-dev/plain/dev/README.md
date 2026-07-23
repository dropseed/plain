# plain.dev

**A single command that runs everything you need for local development.**

![Plain dev command example](https://github.com/dropseed/plain/assets/649496/3643bb64-a99b-4a8e-adab-8c6b81791ea9)

- [Overview](#overview)
- [Commands](#commands)
    - [`plain dev`](#plain-dev)
        - [Services](#services)
        - [Custom processes](#custom-processes)
    - [`plain dev services`](#plain-dev-services)
    - [`plain dev logs`](#plain-dev-logs)
    - [`plain pre-commit`](#plain-pre-commit)
- [Databases](#databases)
    - [A database per checkout](#a-database-per-checkout)
    - [New checkouts start with your data](#new-checkouts-start-with-your-data)
    - [Managing databases](#managing-databases)
    - [Sharing one database between checkouts](#sharing-one-database-between-checkouts)
    - [Switching branches](#switching-branches)
    - [Where the server comes from](#where-the-server-comes-from)
    - [Server lifecycle](#server-lifecycle)
- [`.env` files](#env-files)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

The `plain dev` command starts everything you need for local development with a single command:

```bash
plain dev
```

This will:

- Run preflight checks
- Execute pending migrations
- Start your development server with auto-reload
- Build and watch CSS with Tailwind (if installed)
- Start required services (like databases)
- Run any custom processes you've defined

## Commands

### `plain dev`

The [`plain dev`](./cli.py#cli) command does several things:

- Sets `PLAIN_CSRF_TRUSTED_ORIGINS` to localhost by default
- Runs `plain preflight` to check for any issues
- Executes any pending model migrations
- Starts `gunicorn` with `--reload`
- Serves HTTPS on port 8443 by default (uses the next free port if 8443 is taken and no port is specified)
- Runs `plain tailwind build --watch`, if [`plain.tailwind`](../../plain-tailwind/plain/tailwind/README.md) is installed
- Any custom process defined in `pyproject.toml` at `tool.plain.dev.run`
- Necessary services (ex. Postgres) defined in `pyproject.toml` at `tool.plain.dev.services`

#### Services

Use services to define processes that your app _needs_ to be functional — a
queue, a mail catcher, a search index. They start automatically in `plain dev`,
and also in `plain pre-commit` so preflight and tests have what they need.

```toml
# pyproject.toml
[tool.plain.dev.services]
redis = {cmd = "redis-server --port 6399"}
```

You don't need a service for Postgres — see [Databases](#databases) below.

#### Custom processes

Unlike [services](#services), custom processes are _only_ run during `plain dev`. This is a good place to run something like [ngrok](https://ngrok.com/) or a [Plain job worker](../../plain-jobs/plain/jobs/README.md), which you might need to use your local site, but don't need running for executing tests, for example.

```toml
# pyproject.toml
[tool.plain.dev.run]
    ngrok = {command = "ngrok http $PORT"}
```

### `plain dev services`

Starts your [services](#services) by themselves.
Logs are stored in `.plain/dev/logs/services/`.

### `plain dev logs`

Show output from recent `plain dev` runs.

Logs are stored in `.plain/dev/logs/run/`.

```bash
plain dev logs        # print last log
plain dev logs -f     # follow the latest log
plain dev logs --pid 1234
plain dev logs --path
```

### `plain pre-commit`

A built-in pre-commit hook that you can install with `plain pre-commit --install`.

Runs:

- `uv lock --check`, if using uv
- `plain check` (custom commands, code linting, preflight, migrations, tests)
- `plain assets compile`

Custom commands can be defined in `pyproject.toml` at `tool.plain.check.run` and will run as part of `plain check`:

```toml
[tool.plain.check.run]
my-check = {cmd = "echo 'running my check'"}
```

## Databases

You don't need to configure a database to start working. If [`plain.postgres`](../../plain-postgres/plain/postgres/README.md) is installed and no database URL is set, `plain.dev` provides one — a Postgres server for the project, and a database for this checkout.

```bash
plain dev          # server started, database created and migrated
plain db status    # see what you got
```

**Configuring a URL means "use this, don't manage Postgres for me."** Set `PLAIN_POSTGRES_URL` (or `POSTGRES_URL` in `settings.py`, or `DATABASE_URL`) and `plain.dev` stays out of the way entirely — no server is started and nothing is injected. Nothing here is required, and nothing here overrides you.

### A database per checkout

Every checkout gets its own database, derived from its directory name. Two worktrees of the same project never share data:

| Checkout             | Database        |
| -------------------- | --------------- |
| `myapp/`             | `myapp`         |
| `myapp-feature/`     | `myapp_feature` |
| `worktrees/fix-bug/` | `myapp_fix_bug` |

Test databases are derived from that name too (`test_myapp_feature`), so parallel test runs in different checkouts don't collide either.

All of a project's databases live in one Postgres server, shared by every worktree. That's what makes copying between them instant.

### New checkouts start with your data

A new worktree's database is a **copy of your main database, data included** — because re-seeding a fresh database every time is the actual cost of working in parallel.

```bash
git worktree add ../myapp-feature
cd ../myapp-feature
plain dev          # database forked from `myapp`, with its rows
```

Copying uses `CREATE DATABASE ... TEMPLATE` when the source is idle, which is a file-level copy and effectively instant at any size. If the source is busy — you're running `plain dev` against it in another window — it falls back to a streaming dump/restore, which doesn't interrupt anything. You don't choose; it picks.

Use `plain db create` if you'd rather start empty.

### Managing databases

```bash
plain db status              # this checkout's database, server, size, branch, pending migrations
plain db list                # every database in the project, and who owns it
plain db fork <name>         # copy a database, data and all
plain db use <name>          # point this checkout somewhere else (no name: back to derived)
plain db create [name]       # a new empty database
plain db reset               # drop and recreate this one, empty
plain db drop <name>         # delete a database
plain db clean               # delete databases whose checkout is gone
plain db url                 # print the URL and nothing else, for scripts
```

`plain db status` and `plain db list` take `--json` for scripts and agents.

`plain db url` ensures the server and database exist before printing, and writes
nothing but the URL to stdout, so `export PLAIN_POSTGRES_URL="$(plain db url)"`
is safe to build on.

For a psql prompt on this checkout's database, use [`plain postgres shell`](../../plain-postgres/plain/postgres/README.md) — it connects to whatever database is active, managed or not.

Forks are real copies, so deleted worktrees leave real disk behind. `plain db clean` finds databases whose checkout directory no longer exists and offers to drop them — it never touches a database that doesn't record where it came from, and never the project's main database, which is the fork source for every checkout.

`plain db` changes **which** database you're on; [`plain postgres sync`](../../plain-postgres/plain/postgres/README.md) changes the **schema** of the one you're on. `plain db` exists only when `plain.dev` is installed — it's a development tool with no production counterpart.

### Sharing one database between checkouts

`plain db use` points several checkouts at a single database, which is what you want when you'd rather have no drift than isolation.

The risk is schema, not data: applying a branch-only migration to a shared database changes it for everyone using it. So when `plain dev` sees that combination — a shared database, plus migrations this branch has that it doesn't — it forks you a private copy instead and tells you so. Applying to the shared database is deliberate: `plain db use <name>` to point at it, then `plain postgres sync`.

### Switching branches

Databases remember the branch they were last used on. When you switch branches and the database turns out to be _ahead_ of your code — carrying tables from migrations this branch doesn't have — `plain dev` says so, because nothing else will. Your app keeps working and the schema quietly doesn't match.

It reports and leaves the database alone. `plain db fork` or `plain db reset` are there when you want a clean one.

### Where the server comes from

Docker if it's available, otherwise a Postgres already listening on `127.0.0.1:5432` that accepts the `postgres` role. The second is what makes cloud sandboxes and remote agent environments work, where a Docker daemon usually isn't available but a system Postgres often is.

An open port isn't enough — we check that we can actually log in. Homebrew and
Postgres.app both create a superuser named after your macOS account and no
`postgres` role, so a server like that is reported as unusable rather than
picked and then failed on. Point us at it yourself if you want to use it:

```bash
export PLAIN_POSTGRES_URL="postgres://$USER@127.0.0.1:5432/myapp"
```

```toml
# pyproject.toml
[tool.plain.dev.postgres]
backend = "auto"          # auto | docker | local | off
image = "postgres:16"     # any image, for the docker backend
```

`image` is a full image reference rather than a version number, so you can use a
build that ships the extensions you need:

```toml
[tool.plain.dev.postgres]
image = "pgvector/pgvector:pg16"
```

Changing `image` doesn't rebuild an existing container — the image is fixed when
it's created — so `plain dev` tells you when the two have drifted apart and how
to recreate it. Your data is on a separate volume and survives that.

Data lives in a Docker named volume, never inside your checkout, so deleting a worktree never deletes a database.

Set `backend = "off"` to turn all of this off.

### Server lifecycle

There's one container per project, created the first time something needs a
database. Nothing removes one automatically — a container might hold the only
copy of something — so they accumulate as you work on more projects. Each idle
Postgres holds around 76 MB, which is worth knowing if you have a lot of them.

They deliberately have **no restart policy**, so a reboot leaves them all
stopped and only the projects you actually touch start back up. Starting on
demand costs about two seconds, and the port is re-read each time, so a
reassigned port is handled for you.

```bash
plain db server list      # every project's container on this machine
plain db server stop      # stop it; data is untouched, next command restarts it
plain db server remove    # remove it and its data (--keep-data keeps the volume)
```

`plain db server list` is the one to reach for when Docker feels crowded — it
marks the current project and tells you how many are running.

## `.env` files

`plain.dev` loads `.env` files for any `plain` command run on the dev machine. Production deployments should set environment variables through your platform — Plain does not load `.env` files when `plain.dev` isn't installed.

Files are read in this order (highest precedence first — the first file to define a key wins):

| File                     | Committed? | When loaded                          |
| ------------------------ | ---------- | ------------------------------------ |
| `.env.{PLAIN_ENV}.local` | No         | If `PLAIN_ENV` is set                |
| `.env.local`             | No         | Always, except when `PLAIN_ENV=test` |
| `.env.{PLAIN_ENV}`       | Yes        | If `PLAIN_ENV` is set                |
| `.env`                   | Yes        | Always                               |

Add `.env.local` and `.env.*.local` to your `.gitignore`.

`PLAIN_ENV` is set automatically by the CLI: `plain dev` → `dev`, `plain test` → `test`. Other commands leave `PLAIN_ENV` unset (only `.env.local` and `.env` load). Export `PLAIN_ENV` yourself to override.

Under `PLAIN_ENV=test`, `.env.local` is skipped (matches Next.js and Rails dotenv) so test runs stay deterministic and personal credentials don't leak into the suite. `plain test` sets `PLAIN_ENV=test` for you; the pytest plugin also sets it when `pytest` is invoked directly — and opportunistically loads `.env.test*` if `plain.dev` is installed.

## Settings

| Setting                     | Default            | Env var |
| --------------------------- | ------------------ | ------- |
| `DEV_REQUESTS_IGNORE_PATHS` | `["/favicon.ico"]` | -       |
| `DEV_REQUESTS_MAX`          | `50`               | -       |

See [`default_settings.py`](./default_settings.py) for more details.

## FAQs

#### How do I stop the development server?

You can stop the development server by pressing `Ctrl+C` in the terminal, or by running `plain dev --stop` if it was started in the background.

#### Can I run the server on a different port?

Yes, use the `--port` or `-p` option: `plain dev --port 8000`. If you don't specify a port, it will use 8443 or the next available port.

#### How do I run the server in the background?

Use `plain dev --start` to run the server in the background. You can then use `plain dev --stop` to stop it.

#### What's the difference between services and custom processes?

Services are processes that your app needs to function (like a database). They run during `plain dev` and also during `plain pre-commit`. Custom processes only run during `plain dev` and are typically for development conveniences like ngrok or a job worker.

#### How do I back up a development database?

Forks are the everyday safety copy — `plain db fork` makes an instant, switchable duplicate before you try something risky. For a file that outlives the server itself, plain psql tooling works directly against the database URL:

```bash
pg_dump -Fc "$(plain db url)" > myapp.backup
```

#### Why am I seeing deprecation warnings?

The development server is configured to show `DeprecationWarning` and `PendingDeprecationWarning` messages so you can catch deprecated code before it breaks in future versions. You can override this by setting your own `PYTHONWARNINGS` environment variable.

## Installation

Install the `plain.dev` package from [PyPI](https://pypi.org/project/plain.dev/):

```bash
uv add plain.dev --dev
```

Note: The `plain.dev` package does not need to be added to `INSTALLED_PACKAGES`.
