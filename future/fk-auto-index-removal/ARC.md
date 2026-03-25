# FK auto-index removal

Remove the implicit `db_index=True` default on ForeignKeyField and require explicit names on all `Index` objects — making every index in a Plain app visible, named, and intentional.

Plain inherited Django's auto-FK-indexing behavior, which creates redundant indexes wherever a FK column is already the leading column of a composite index or unique constraint. The diagnose command found 8 redundant auto-indexes in Plain's own packages and 16 on a production app.

The safety net is already in place: preflight warns about uncovered FK columns, diagnose catches DB-level gaps, and unique constraints are correctly counted as index coverage everywhere.

## Sequence

- [x] [index-require-name](index-require-name.md)
- [ ] [remove-index-auto-naming](remove-index-auto-naming.md)
- [ ] [fk-remove-auto-index](fk-remove-auto-index.md)
