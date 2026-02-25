# plain-models: Promote POSTGRES_OPTIONS keys to named settings

- `POSTGRES_OPTIONS` is currently a catch-all dict passed to psycopg
- Some keys are Plain-specific (extracted and handled specially by the wrapper)
- Others are straight psycopg pass-through
- Promoting common ones to named settings would make them discoverable and configurable via env vars

## Plain-specific keys (currently popped out of OPTIONS)

- `isolation_level` — transaction isolation level (defaults to READ_COMMITTED)
- `server_side_binding` — use server-side parameter binding cursors
- `assume_role` — runs `SET ROLE` after connecting

## Common psycopg/libpq keys

- `sslmode` — SSL negotiation mode (`disable`, `require`, `verify-full`, etc.)
- `sslrootcert`, `sslcert`, `sslkey` — SSL certificate paths
- `service` — PostgreSQL service name (from `pg_service.conf`)
- `passfile` — password file path
- `prepare_threshold` — prepared statement threshold (disabled by default for connection pooler compatibility)

## Potential new settings

```python
POSTGRES_SSL_MODE: str = ""
POSTGRES_ISOLATION_LEVEL: str = "read_committed"
POSTGRES_SERVER_SIDE_BINDING: bool = False
POSTGRES_ASSUME_ROLE: str = ""
```

## Considerations

- SSL settings are the most commonly needed (cloud databases often require `sslmode=require`)
- These are currently settable via DATABASE_URL query string (`?sslmode=require`) which is convenient
- Keep `POSTGRES_OPTIONS` as an escape hatch for anything not promoted to a named setting
- Don't over-promote — only settings that are commonly configured deserve named settings
