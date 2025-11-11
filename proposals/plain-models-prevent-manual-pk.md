# plain-models: Prevent Manual Primary Key Setting

**Prevent users from setting auto-generated primary keys during `Model.__init__()`, forcing them to use query methods instead.**

## Problem

Currently, users can manually set the primary key when instantiating a model:

```python
# This works but is confusing
user = User(id=1, email="test@example.com")
```

This creates several issues:

1. **Ambiguous intent**: Is this creating a new object or referencing an existing one?
2. **State confusion**: The object has `_state.adding=True` (new) but has a primary key (suggests existing)
3. **Bypasses query layer**: Users should use `User.query.get(id=1)` to retrieve existing objects
4. **Inconsistent with philosophy**: Plain uses auto-increment IDs only, not user-provided primary keys

## Solution

Block setting auto-generated primary keys in `Model.__init__()`:

```python
# This should raise ValueError
user = User(id=1, email="test@example.com")
# ValueError: Cannot set auto-generated primary key 'id' during initialization.
# Use User.query.get() to retrieve existing objects.

# Users must do this instead
user = User.query.get(id=1)
```

## Implementation Approach

### 1. Add `_from_db` parameter to `__init__`

Modify `Model.__init__()` to accept an internal `_from_db` flag:

```python
class Model:
    def __init__(self, *, _from_db: bool = False, **kwargs: Any):
        if not _from_db:
            # Validate that auto-generated PKs are not being set
            meta = self._model_meta
            for key in kwargs:
                try:
                    field = meta.get_field(key)
                    if field.primary_key and getattr(field, "auto_created", False):
                        raise ValueError(
                            f"Cannot set auto-generated primary key '{field.name}' during initialization. "
                            f"Use {self.__class__.__name__}.query.get() to retrieve existing objects."
                        )
                except FieldDoesNotExist:
                    pass

        # ... rest of __init__ logic
```

### 2. Update `from_db()` to pass `_from_db=True`

The `from_db()` classmethod needs to bypass this validation when loading from the database:

```python
@classmethod
def from_db(cls, field_names: Iterable[str], values: Sequence[Any]) -> Model:
    # ... build field_dict from field_names and values ...

    # Pass _from_db=True to allow setting the PK
    new = cls(_from_db=True, **field_dict)
    new._state.adding = False
    return new
```

### 3. Use `auto_created` attribute to identify auto-generated PKs

Only block fields where `field.primary_key=True` AND `field.auto_created=True`. This attribute is:

- Set to `True` only on `PrimaryKeyField` (the automatic `id` field)
- Set to `False` on all other field types

This ensures we only block the automatic `id` field, not user-defined primary keys (if we ever support them).

## Benefits

1. **Clearer intent**: `User(id=1)` is clearly an error - use `User.query.get(id=1)` instead
2. **Consistent state**: Objects from `__init__()` are always new (`_state.adding=True`, `id=None`)
3. **Better errors**: Users get a helpful error message pointing them to the correct API
4. **Type safety**: Aligns with Plain's opinionated approach of only supporting auto-increment IDs

## Drawbacks

1. **Breaking change**: Any code setting `id` in `__init__()` will break
2. **Extra validation**: Small performance overhead in `__init__()` (iterating kwargs to check fields)
3. **Internal flag**: The `_from_db` parameter is an internal detail that must be maintained

## Edge Cases

### What about `pk` alias?

Plain doesn't support Django's `pk` alias, so we only need to check for the actual field name (`id`).

### What if someone has a custom primary key?

Currently Plain only supports auto-increment integer IDs. If we ever add support for custom primary keys (UUIDs, natural keys, etc.), the `auto_created` attribute already distinguishes:

- `PrimaryKeyField`: `auto_created=True` → blocked
- User-defined UUID/natural key: `auto_created=False` → allowed

### What about `from_db()` compatibility?

By adding the `_from_db` parameter, we ensure `from_db()` continues to work and custom `__init__()` logic in subclasses still runs (unlike approaches that bypass `__init__` entirely).

## Testing

Add test case:

```python
def test_cannot_set_auto_generated_id_in_init(db):
    """Test that setting auto-generated id in __init__ raises ValueError."""
    with pytest.raises(
        ValueError,
        match=r"Cannot set auto-generated primary key 'id'.*Car\.query\.get\(\)",
    ):
        Car(id=1, make="Toyota", model="Tundra")
```

## Related Work

- **Proposal**: `plain-models-explicit-create-update.md` - Related effort to make model operations more explicit
- **Current behavior**: Plain only supports auto-increment IDs, this formalizes that constraint

## Open Questions

1. **Should we allow bypassing this restriction?**
    - Maybe a `_allow_pk=True` parameter for advanced use cases?
    - Or keep it strict to maintain consistency?

2. **Performance impact?**
    - The validation loop in `__init__()` iterates all kwargs
    - Could optimize by checking only if `'id'` in kwargs (assumes default PK name)
    - Trade-off: optimization vs. future flexibility for custom PK names

## Implementation Status

Not yet implemented. This proposal documents the approach explored in conversation but deferred for further consideration.
