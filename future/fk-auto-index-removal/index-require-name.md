# Require explicit names on Index

Done. All `Index` objects now require a `name` argument. The `{table}_{column}_idx` convention is used across Plain's packages. `max_name_length` updated from 30 (Django legacy) to 63 (Postgres identifier limit).

The `/plain-upgrade` skill adds the current auto-generated name as an explicit `name=` argument to existing unnamed indexes, then `makemigrations` generates `RenameIndex` operations to the new clean names. Instant `ALTER INDEX RENAME` — no data touched.
