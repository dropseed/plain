# Development

## Dev Server

Run `uv run plain dev` to start the development server with auto-reload and HTTPS.

The server URL will be displayed (typically `https://<project>.localhost:8443`).

View logs: `uv run plain dev logs`

## Tunnel URL

If `plain dev logs` shows a `Tunnel running at https://<subdomain>.plaintunnel.com`
line, that tunnel URL is the canonical app URL — use it for browser navigation,
screenshots, and shared links. Use the localhost `Server running at ...` URL only
when there's no tunnel, or for local CLI checks (`curl`, `plain request`).

## Worktrees and `.plain/`

- `.plain/` holds a checkout's disposable _artifacts_ — logs, compiled assets,
  certificates. It's rebuilt automatically, so there's nothing in it worth
  sharing, but sharing it between checkouts is at worst confusing, not
  corrupting: the _facts_ that decide which database and which dev server are
  this checkout's live outside it (see below), so a shared `.plain/` can't
  cross-contaminate them.
- Downloaded tool binaries (Tailwind, Oxc, mkcert) are cached machine-wide in
  `~/.cache/plain`, and each worktree's database is forked from the main
  checkout's data (see below).

## Dev databases

A database URL is never required. With `plain.postgres` installed and no URL
configured, plain-dev provides a Postgres server per project and a database per
checkout. Setting `PLAIN_POSTGRES_URL` (or `POSTGRES_URL` in settings) means
"use this" and turns all of it off.

- Each checkout gets its own database derived from the directory name, so
  worktrees never share data. Test databases derive from it too.
- A new worktree's database is forked from the project's main database **with
  its data** — don't re-seed by hand, and don't tell users to.
- `plain db status --json` before diagnosing anything database-shaped: database,
  server, size, branch, and pending migration count. `plain db list --json` for
  every database in the project and which checkout owns it.
- `plain postgres shell` for a psql prompt on the active database; it accepts
  piped SQL, so `echo 'select ...' | plain postgres shell` is the way to inspect
  data.
- `plain db clean` drops databases whose checkout directory is gone. Forks are
  full copies, so deleted worktrees do leave disk behind.
- One Postgres container per project, started on demand and never removed
  automatically. `plain db server list` shows them all, `plain db server stop`
  frees one up (~76MB each), `plain db server remove` deletes it and its data.
- `plain db` is for _which_ database; `plain postgres sync` is for its schema.
  Don't reach for one to do the other's job.
- Facts about a checkout — which database it uses, whether its dev server is
  running — live outside it, keyed by its path (under `PLAIN_CACHE_PATH`), so
  copying or symlinking a working tree can't make two checkouts share a
  database or a dev slot. Change the database with `plain db use`, not by
  editing files. `.plain/` keeps only artifacts: logs, compiled assets, certs.

Run `uv run plain docs dev` for the full picture.
