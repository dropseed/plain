"""Managed Postgres for local development.

A database URL is never required. If you configure one, we use it and stay out
of the way. If you don't, plain-dev provides one: a Postgres server per project,
and a database per checkout that starts as a copy of your main database's data.

The pieces (import from the submodule that owns the name):

- `identity` — what this project and checkout are called, and which database
  they own. All derived; the only stored state is a pointer file written when
  you explicitly reassign a checkout.
- `backends` — where the server comes from (Docker, or a local Postgres).
- `cluster` — dev's policy on top of that server: metadata and forking.
- `resolve` — whether to take over at all, and the URL if we do.
- `guard` — protecting a shared database from a branch's migrations.
- `branch_switch` — noticing a database left behind by a branch switch.
- `schema_state` — how far apart the database and the code's migrations are.
"""
