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

## Dev databases

A database URL is never required. With `plain.postgres` installed and no URL
configured, plain-dev provides a Postgres server per project and a database per
checkout. Setting `PLAIN_POSTGRES_URL` (or `POSTGRES_URL` in settings) means
"use this" and turns all of it off.

- Each checkout gets its own database derived from the directory name, so
  worktrees never share data. Test databases derive from it too.
- A new worktree's database is forked from the project's main database **with
  its data** — don't re-seed by hand, and don't tell users to.
- `plain db status` before diagnosing anything database-shaped: it shows the
  database, server, size, branch, and pending migrations.
- `plain db clean` drops databases whose checkout directory is gone. Forks are
  full copies, so deleted worktrees do leave disk behind.
- One Postgres container per project, started on demand and never removed
  automatically. `plain db server list` shows them all, `plain db server stop`
  frees one up (~76MB each), `plain db server remove` deletes it and its data.
- Never edit `.plain/dev/postgres-url` — it's a derived cache, repaired
  automatically. `.plain/dev/database` is the pointer written by `plain db use`.

Run `uv run plain docs dev` for the full picture.
