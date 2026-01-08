# ForeignKeyField Redesign: Partial Instance with Deferred Loading

## Problem Statement

When defining `author: User = ForeignKeyField(User, ...)`, Plain auto-generates `author_id` attribute. This creates two issues:

1. Type checkers don't know about `author_id: int`
2. Two separate attributes (`author` and `author_id`) is awkward

## Proposed Solution: Partial Instance Pattern

**Core idea:** Return a real User instance with only `id` populated. Other fields are deferred and load on access via existing `refresh_from_db` infrastructure.

### Current Behavior

```python
post.author      # Fetches full User from DB
post.author_id   # Returns int (stored in __dict__)
```

### New Behavior

```python
post.author      # Returns partial User with only id (no query)
post.author.id   # Returns int (no query)
post.author.name # Triggers refresh_from_db, returns name
```

**Why this works:**

- Plain already has deferred field loading via `Field.__get__` (line 867-869 in fields/**init**.py)
- When a field isn't in `__dict__`, it calls `refresh_from_db()`
- We create a partial instance with only `id` in `__dict__`
- All other field accesses trigger the existing deferred loading

**Benefits over ForeignKeyRef:**

- No new class needed
- `isinstance(post.author, User)` returns True naturally (it IS a User)
- Uses existing infrastructure
- Type checkers already work

---

## Implementation Design

### Modified: `ForwardForeignKeyDescriptor.__get__`

```python
def __get__(self, instance, cls):
    if instance is None:
        return self

    # Check cache - might have full instance from select_related
    try:
        return self.field.get_cached_value(instance)
    except KeyError:
        pass

    # Get raw FK value
    pk_value = instance.__dict__.get(self.field.attname)
    if pk_value is None:
        if self.field.allow_null:
            return None
        raise self.RelatedObjectDoesNotExist(...)

    # Create partial instance with only id populated
    model = self.field.remote_field.model
    partial = model.__new__(model)  # Bypass __init__
    partial._state = ModelState()
    partial._state.adding = False  # Not a new object
    partial.__dict__['id'] = pk_value  # Only id is set
    # All other fields deferred (not in __dict__)

    # Cache and return
    self.field.set_cached_value(instance, partial)
    return partial
```

When `partial.name` is accessed:

1. `Field.__get__` sees `'name'` not in `partial.__dict__`
2. Calls `partial.refresh_from_db(fields=['name'])`
3. `refresh_from_db` queries by `partial.id` (line 306: `filter(id=self.id)`)
4. Populates `partial.__dict__['name']`

---

## Design Decisions (Confirmed)

1. **Remove `_id` pattern entirely** - No `author_id` attribute exposed
2. **`isinstance(post.author, User)` returns True** - naturally, since it's a real User instance
3. **No new ForeignKeyRef class** - use existing deferred loading
4. **Accept int directly in `__init__`** - `Post(author=1)` sets FK by ID without query

---

## Detailed Implementation

### Storage Changes

Keep `author_id` in `__dict__` for internal FK storage (needed for DB operations), but don't expose it as a Python attribute. The `ForwardForeignKeyDescriptor` handles all access via `.author`.

Actually, we can keep the current storage unchanged:

- `post.__dict__['author_id']` = raw FK value (for DB)
- `post.author` = partial User instance (via descriptor)

No `_fk_values` dict needed.

### Model.**init** Changes

Accept both int (FK ID) and Model instance:

```python
def __init__(self, **kwargs):
    for field in meta.fields:
        if isinstance(field, ForeignKeyField):
            try:
                value = kwargs.pop(field.name)
                if isinstance(value, int):
                    # Post(author=1) - just the ID
                    self.__dict__[field.attname] = value  # author_id = 1
                elif isinstance(value, Model):
                    # Post(author=user) - extract ID, cache instance
                    self.__dict__[field.attname] = value.id
                    field.set_cached_value(self, value)
                elif value is None:
                    if field.allow_null:
                        self.__dict__[field.attname] = None
                    else:
                        raise ValueError(...)
            except KeyError:
                # Use default
                ...
```

**Remove** the `field.attname` (e.g., `author_id`) kwarg handling entirely. Only accept `field.name` (e.g., `author`).

### Attribute Access Prevention

To prevent `post.author_id` from being accessible, we need to NOT register the field descriptor at `attname`. Currently in `Field.contribute_to_class()`:

```python
if self.column:
    setattr(cls, self.attname, self)  # Sets cls.author_id = FieldDescriptor
```

For ForeignKeyField, we should skip this or override it:

```python
# In ForeignKeyField.contribute_to_class()
def contribute_to_class(self, cls, name):
    super().contribute_to_class(cls, name)
    # Remove the attname descriptor that was set by parent
    # We only want access via field.name (author), not attname (author_id)
    if hasattr(cls, self.attname):
        delattr(cls, self.attname)
```

Or better: override in ForeignKeyField to not set the attname descriptor in the first place.

---

## Files to Modify

| File                                         | Changes                                   |
| -------------------------------------------- | ----------------------------------------- |
| `plain/models/fields/related_descriptors.py` | Return partial instance in `__get__`      |
| `plain/models/fields/related.py`             | Don't set descriptor at `attname`         |
| `plain/models/base.py`                       | Accept int/Model for FK in `__init__`     |
| `plain/models/fields/__init__.py`            | Possibly: FK-specific descriptor handling |

---

## Edge Cases

1. **Nullable FK**: Return `None` directly (no partial instance)
2. **select_related**: Caches full instance, partial never created
3. **Prefetching**: Same - full instance cached
4. **Multiple FK access**: Each creates own partial, but refresh_from_db updates **dict**
5. **Saving partial**: `partial.save()` would fail without all required fields - need to handle

---

## Testing Strategy

1. `post.author.id` returns int, no query
2. `post.author.name` triggers exactly one query
3. `isinstance(post.author, User)` returns True
4. `post.author == user` compares by pk
5. `post.author = user` works
6. `post.author = 1` works (set by ID)
7. `post.author_id` raises AttributeError (not accessible)
8. `select_related('author')` returns full instance
