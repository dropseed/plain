# Remove Index auto-naming

Now that all indexes have explicit names, remove `set_name_with_model` and the auto-naming machinery from `Index`.

## What to remove

- `Index.set_name_with_model()` — the hash-based auto-naming function
- The `if not index.name: index.set_name_with_model(model)` calls in `meta.py` and `options.py`
- The `names_digest` and `split_identifier` imports from `indexes.py`

## What to keep

- `set_name_with_model` is still called during migration state reconstruction for old migrations that had auto-named indexes. Once all users have migrated past the rename migrations (from `index-require-name`), this code path is dead. Can be removed after one release cycle.
- `Index.__init__` already requires `name` — no change needed there.

## When

Safe to do one release after `index-require-name` ships, to give users time to run the rename migrations.
