# plain-models: Move max_length to specific Field types

- `max_length` is currently defined on the base `Field` class but only used by a few field types
- Move `max_length` to only the fields that actually use it: `CharField`, `BinaryField`
- Integer fields have a warning check (`_check_max_length_warning`) that would become unnecessary

## Current state

- Base `Field.__init__()` accepts `max_length` parameter (line 179)
- Only meaningful for: `CharField`, `BinaryField`, `EmailField`, `URLField`, `GenericIPAddressField`, `UUIDField`
- `IntegerField` warns if `max_length` is passed (but still accepts it)
- Other fields silently ignore it

## Implementation

- Remove `max_length` from base `Field` class
- Add `max_length` to `CharField` and `BinaryField` directly
- `EmailField`/`URLField` inherit from `CharField` so they get it automatically
- `GenericIPAddressField`/`UUIDField` set it internally, can define it locally
- Move choice length validation from `Field._check_choices()` to `CharField._check_choices()`
- Update `deconstruct()` to handle `max_length` in subclasses
- Remove `IntegerField._check_max_length_warning()` (no longer needed)

## Benefits

- Cleaner API - fields only accept parameters they use
- Better type checking - no spurious `max_length` on `IntegerField`
- Easier to understand which fields support which options
