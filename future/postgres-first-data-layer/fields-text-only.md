---
related:
  - models-field-max-length
---

# Remove CharField, use TextField for all strings

PostgreSQL makes no distinction between `varchar`, `varchar(n)`, and `text` — they use the same storage, same performance. The only difference is that `varchar(n)` adds an implicit length check. The PostgreSQL wiki explicitly recommends against using `varchar(n)` by default.

Plain should reflect this: one string field type backed by `text`, with length validation as a separate concern.

## Changes

### Delete CharField, keep TextField

- Remove `CharField` entirely
- `TextField` becomes the single string field, always mapping to `text`
- Add optional `max_length` parameter to `TextField` — purely for Python-layer validation (adds `MaxLengthValidator`), does NOT affect the database column type
- Move CharField's `to_python()` / `get_prep_value()` into TextField (they're identical)

### EmailField and URLField become TextField subclasses

- `EmailField(TextField)` — keeps email validator, drops `max_length=254` default (just `text`)
- `URLField(TextField)` — keeps URL validator, drops `max_length=200` default (just `text`)
- Both still accept optional `max_length` for Python validation if the user wants it

### Database type mapping

- Remove `CharField` entry from `DATA_TYPES` and `_get_varchar_column`
- `TextField` stays as `"text"`
- Remove `CAST_CHAR_FIELD_WITHOUT_MAX_LENGTH`

### max_length is validation only, not schema

`max_length` on TextField adds a `MaxLengthValidator` — it does not change the column type or generate a check constraint. This means:

- Changing `max_length` never requires a migration
- Users who want DB-level enforcement add a `CheckConstraint` explicitly (same pattern as any other business rule)
- This matches how `PositiveIntegerField` works today: the `>= 0` check constraint is explicit in `DATA_TYPE_CHECK_CONSTRAINTS`, not hidden inside the field

### Migration handling

When users upgrade and their CharField columns become TextField:

- The migration autodetector will see the field type change and generate `AlterField` operations
- These produce `ALTER TABLE ... ALTER COLUMN ... TYPE text` — which is effectively a no-op in PostgreSQL (varchar and text are the same internally)
- The `/plain-upgrade` agent rewrites `types.CharField(...)` → `types.TextField(...)` in user code

### Forms CharField → TextField

Rename forms `CharField` to `TextField` for consistency. There's no forms `TextField` today — the distinction between "char" and "text" never meant anything in the forms layer either.

- Rename `plain.forms.CharField` to `plain.forms.TextField`
- Subclasses (`EmailField`, `URLField`, `RegexField`, `UUIDField`, `JSONField`) inherit from `TextField` instead
- Update `modelfield_to_formfield()` — the `isinstance(modelfield, postgres.CharField)` branch gets deleted, the `isinstance(modelfield, postgres.TextField)` branch returns `forms.TextField`
- The `/plain-upgrade` agent handles the rename in user code

### Cleanup

- Remove model `CharField` from `__all__`, exports, and type mappings
- Remove `_get_varchar_column` from dialect.py
- Remove `CAST_CHAR_FIELD_WITHOUT_MAX_LENGTH`
- Update `models-field-max-length` future — `max_length` still needs to move off the base `Field` class, but now it moves to `TextField` and `BinaryField` instead of `CharField` and `BinaryField`
