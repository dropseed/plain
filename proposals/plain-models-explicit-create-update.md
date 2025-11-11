# plain-models: Explicit create() and persist() Methods

**Replace the ambiguous `save()` method with explicit `create()` and `persist()` instance methods.**

## Problem

The current `save()` method has an ambiguous API that tries to be smart:

- If object has a PK and is not "adding" → try UPDATE
- If UPDATE affects 0 rows → fall back to INSERT
- Track state via `_state.adding` flag

This creates several issues:

1. **Ambiguous intent**: Code doesn't clearly express whether it's creating or updating
2. **Wasted queries**: "Try UPDATE then INSERT" pattern when it could be direct
3. **Unclear API**: Users must understand `force_insert` and `force_update` parameters
4. **Implicit behavior**: The decision to INSERT vs UPDATE is hidden in the implementation
5. **Testing difficulty**: Hard to verify which operation actually occurred

## Solution

Replace `save()` with two explicit methods:

```python
# Create - always INSERT
user = User(email="test@example.com")
user.create()  # Raises error if already persisted

# Persist - always UPDATE
user.email = "new@example.com"
user.persist()  # Raises error if not persisted
```

## Key Research Findings

### 1. `_state.adding` Remains the Source of Truth

After comprehensive codebase analysis, `_state.adding` is currently used in 6 places:

1. **`base.py:524`** - Save optimization: skip UPDATE for new objects with default PK
2. **`base.py:750`** - Skip PK uniqueness validation when updating existing object
3. **`base.py:766`** - Exclude self from uniqueness queries when updating
4. **`constraints.py:410`** - Exclude self from constraint queries when updating
5. **`forms.py:395`** - Display "created" vs "changed" message
6. **`related_managers.py:176`** - Prevent bulk ops on unsaved objects

**With explicit methods, `_state.adding` remains necessary** to track persistence state. The explicit methods (`create()`/`update()`) clarify intent while `_state.adding` ensures correctness in validation and related manager operations.

### 2. `pre_save()` Uses Operation Type, Not `_state.adding`

Critical finding: `Field.pre_save(obj, add)` parameter comes from the operation type:

- **INSERT operations** → always `add=True` (`compiler.py:1667`)
- **UPDATE operations** → always `add=False` (`base.py:536`)

This is **decoupled from `_state.adding`** and works perfectly with explicit methods:

- `create()` calls `pre_save(obj, add=True)`
- `update()` calls `pre_save(obj, add=False)`

No changes needed to existing field implementations (`DateTimeField`, `PasswordField`, etc.)!

### 3. Why `_state.adding` Is Needed

**Plain only supports auto-increment IDs**, where `id is None` for new objects and `id is not None` for persisted objects. Manual PK assignment is not allowed.

**`_state.adding` provides the canonical way to track persistence state:**

```python
# New object
obj = MyModel(name="test")
print(obj.id)              # None
print(obj._state.adding)   # True

# After creation
obj.create()
print(obj.id)              # 1 (auto-assigned)
print(obj._state.adding)   # False
```

**With explicit methods:** `_state.adding` remains the source of truth for whether an object has been persisted. The explicit `create()`/`persist()` methods make the developer's intent clear while `_state.adding` ensures correctness in validation and related manager operations.

### 4. Deferred Fields Are Auto-Detected

When loading with `.only()` or `.defer()`, `save()` auto-detects deferred fields by checking if they're in `__dict__`:

```python
user = User.query.only('email').get(id=1)
user.email = "new@example.com"
user.save()  # Automatically only updates 'email', not other fields
```

**Implementation in `base.py:436-445`**: If deferred fields exist and no explicit `update_fields`, use only loaded fields.

**For explicit `update()`:** Keep this behavior when `update_fields=None`.

### 5. Related Field Validation Doesn't Use `_state.adding`

The `_prepare_related_fields_for_save()` method (`base.py:601-639`) validates that foreign keys don't point to unsaved objects.

**Key finding:** It only checks `if obj.id is None`, not `_state.adding`.

**With explicit methods:** Just pass operation name for error messages:

- `create()` → `_prepare_related_fields_for_save("create")`
- `update()` → `_prepare_related_fields_for_save("update")`

### 6. Migrations Don't Depend on Instance Methods

Migrations use schema operations, not model instances. The only exception is `MigrationRecorder` which uses `QuerySet.create()`, not `instance.save()`.

**Impact:** Zero. Migrations unaffected by this change.

### 7. `update_or_create()` Auto-Adds Fields with Custom `pre_save()`

Found in `query.py:912-927`: When determining `update_fields`, it automatically includes fields that have custom `pre_save()` methods (like `auto_now` fields).

**For explicit `update()`:** Replicate this - when `update_fields=None`, auto-include fields with custom `pre_save()`.

## Proposed API Design

### Instance Methods

```python
class Model:
    def create(
        self,
        *,
        clean_and_validate: bool = True,
    ) -> Self:
        """
        Insert this instance into the database.

        Raises:
            ValueError: If object already persisted (use update() instead)
            ValidationError: If validation fails
            IntegrityError: If database constraints violated

        Returns:
            self (for chaining)
        """
        if not self._state.adding:
            raise ValueError(
                f"Cannot create() {self.__class__.__name__} that is already persisted. "
                f"Use update() instead."
            )

        # CRITICAL: Wrap in transaction rollback guard
        with transaction.mark_for_rollback_on_error():
            self._prepare_related_fields_for_save("create")

            if clean_and_validate:
                self.full_clean()

            self._insert()  # Always INSERT

        # Only mark as persisted if INSERT succeeded
        self._state.adding = False
        return self

    def persist(
        self,
        *,
        clean_and_validate: bool = True,
        update_fields: Iterable[str] | None = None,
    ) -> Self:
        """
        Persist this instance to the database (UPDATE operation).

        Args:
            update_fields: Only update these fields. If None, auto-detects:
                - Loaded fields (if deferred fields exist)
                - Fields with custom pre_save() methods

        Raises:
            ValueError: If object not persisted (use create() instead)
            FieldError: If trying to update deferred fields explicitly
            ValidationError: If validation fails

        Returns:
            self (for chaining)
        """
        if self._state.adding:
            raise ValueError(
                f"Cannot persist() {self.__class__.__name__} that hasn't been created yet. "
                f"Use create() instead."
            )

        # Auto-detect deferred fields
        if update_fields is None:
            deferred = self.get_deferred_fields()
            if deferred:
                # Only update loaded fields
                update_fields = self._get_loaded_field_names() - deferred
            else:
                # Include fields with custom pre_save()
                update_fields = self._get_fields_for_update()
        else:
            # Validate no deferred fields in explicit update_fields
            deferred = self.get_deferred_fields()
            invalid = set(update_fields) & deferred
            if invalid:
                raise FieldError(
                    f"Cannot update deferred fields: {', '.join(invalid)}"
                )

        # CRITICAL: Convert field names to Field objects for _prepare_related_fields_for_save
        # _prepare_related_fields_for_save expects Field objects, not strings
        field_objects = None
        if update_fields:
            field_objects = [
                self._model_meta.get_field(name) for name in update_fields
            ]

        # CRITICAL: Wrap in transaction rollback guard
        with transaction.mark_for_rollback_on_error():
            self._prepare_related_fields_for_save("persist", field_objects)

            if clean_and_validate:
                self.full_clean(exclude=self._get_excluded_fields(update_fields))

            self._do_update(update_fields)  # Always UPDATE

        return self
```

### QuerySet Method Changes

```python
class QuerySet:
    # REMOVE: QuerySet.create() - redundant with instance.create()
    # Users should do: obj = Model(**kwargs); obj.create()

    # KEEP: QuerySet.update() - bulk operations (different purpose)
    def update(self, **kwargs) -> int:
        """Bulk update - no validation, no instance loading"""
        ...

    # KEEP: get_or_create() - query operation, not instance method
    # CRITICAL: Preserves transaction safety and retry logic
    def get_or_create(self, defaults=None, **kwargs):
        self._for_write = True
        try:
            return self.get(**kwargs), False
        except self.model.DoesNotExist:
            params = self._extract_model_params(defaults, **kwargs)
            # CRITICAL: Atomic transaction with retry on IntegrityError
            try:
                with transaction.atomic():
                    # CRITICAL: Resolve callable defaults
                    params = dict(resolve_callables(params))
                    obj = self.model(**params)
                    obj.create()  # Changed from: self.create(**params)
                    return obj, True
            except (IntegrityError, ValidationError):
                # Race condition: another process created it
                # Try to get the existing object
                try:
                    return self.get(**kwargs), False
                except self.model.DoesNotExist:
                    pass
                raise

    # KEEP: update_or_create() - query operation, not instance method
    # CRITICAL: Preserves locking and auto_now field handling
    def update_or_create(
        self,
        defaults=None,
        create_defaults=None,
        **kwargs
    ):
        if create_defaults is None:
            update_defaults = create_defaults = defaults or {}
        else:
            update_defaults = defaults or {}

        self._for_write = True
        # CRITICAL: Atomic transaction with select_for_update locking
        with transaction.atomic():
            # Lock the row to prevent concurrent updates
            obj, created = self.select_for_update().get_or_create(
                create_defaults, **kwargs
            )
            if created:
                return obj, created

            # CRITICAL: Resolve callable defaults
            for k, v in resolve_callables(update_defaults):
                setattr(obj, k, v)

            # CRITICAL: Build update_fields with auto_now fields
            update_fields = set(update_defaults)
            concrete_field_names = self.model._model_meta._non_pk_concrete_field_names
            if concrete_field_names.issuperset(update_fields):
                # Add fields with custom pre_save() (e.g. auto_now)
                for field in self.model._model_meta.local_concrete_fields:
                    if not (
                        field.primary_key
                        or field.__class__.pre_save is Field.pre_save
                    ):
                        update_fields.add(field.name)
                        if field.name != field.attname:
                            update_fields.add(field.attname)

                obj.persist(update_fields=update_fields)
            else:
                obj.persist()

        return obj, created
```

#### Why Remove QuerySet.create() But Keep get_or_create()?

**For direct usage, QuerySet.create() is redundant:**

```python
# Same verbosity, same result
User.query.create(email="test@example.com")
User(email="test@example.com").create()
```

**However, related managers need updating!**

Related managers currently delegate to `QuerySet.create()` to auto-populate foreign keys:

```python
# Current implementation (related_managers.py:193-196)
class ReverseManyToOneManager:
    def create(self, **kwargs):
        self._check_fk_val()
        kwargs[self.field.name] = self.instance  # Auto-inject parent FK
        return self.model.query.create(**kwargs)
```

**With instance methods, related managers call `instance.create()` instead:**

```python
# New implementation
class ReverseManyToOneManager:
    def create(self, **kwargs):
        self._check_fk_val()
        kwargs[self.field.name] = self.instance  # Auto-inject parent FK
        new_obj = self.model(**kwargs)  # Instantiate with FK
        return new_obj.create()  # Use instance method
```

This **preserves all functionality**:

```python
parent = Parent.query.create(name="Test")
child = parent.children.create()  # child.parent still auto-set ✅
assert child.parent == parent
```

**Key insight:** QuerySet context (filters, hints, etc.) is NOT needed for create operations. You don't filter before creating - you create a new object directly.

**get_or_create() is fundamentally different:**

1. **It's a query operation first** - queries database before creating
2. **Supports QuerySet chaining:**
    ```python
    # Filter context matters for the GET operation
    user, created = User.query.filter(active=True).get_or_create(
        email="test@example.com",
        defaults={"active": True}
    )
    ```
3. **Required for related managers:**
    ```python
    # Related managers are QuerySets
    post, created = user.posts.get_or_create(title="Test")
    ```
4. **Handles race conditions** with transactions (requires QuerySet context)

**Important: MigrationRecorder also uses QuerySet.create()**

The `MigrationRecorder` (line 109 in `migrations/recorder.py`) tracks applied migrations:

```python
self.migration_qs.create(app=app, name=name)
```

**Decision needed:**

1. **Keep `QuerySet.create()`** for internal use (MigrationRecorder, easier migration for related managers)
    - Mark as "internal" or "discouraged" for user code
    - Internally delegates to `Model(**kwargs).create()`
2. **Remove `QuerySet.create()`** entirely
    - Update `MigrationRecorder` to use `Model(**kwargs).create()`
    - Update all 6 related manager methods to use instance method

**Recommendation:** Keep `QuerySet.create()` but mark as internal/legacy. This provides a smoother migration path and doesn't break MigrationRecorder.

### Return Values

**Both `create()` and `persist()` return `self`** for chaining:

```python
# Create and immediately use
user = User(email="test@example.com").create()

# Persist and chain additional operations
user.persist().refresh_from_db()
```

This is consistent between methods and enables method chaining. Unlike `QuerySet.update()` which returns an int (rows affected) for bulk operations, instance methods return `self` since you're always operating on a single object.

**Note:** `persist()` is an instance method, while `QuerySet.update()` is a bulk operation. They have different purposes and APIs:

```python
# QuerySet.update() - bulk operation, takes field values
User.query.update(email="new@example.com")  # Returns int (rows affected)

# Instance persist() - persists object state to database
user.email = "new@example.com"
user.persist()  # Returns self
```

## Error Handling

### ValueError Cases

```python
# Trying to create already-persisted object
obj = User.query.get(id=1)
obj.create()
# ValueError: Cannot create() User that is already persisted. Use persist() instead.

# Trying to persist unpersisted object
obj = User(email="test@example.com")
obj.persist()
# ValueError: Cannot persist() User that hasn't been created yet. Use create() instead.
```

### FieldError Cases

```python
# Trying to update deferred fields
user = User.query.only('name').get(id=1)
user.update(update_fields=['email'])  # email is deferred
# FieldError: Cannot update deferred fields: email
```

### ValidationError Cases

```python
# Validation errors (same as current)
user = User(email="invalid")
user.create()
# ValidationError: Enter a valid email address.
```

### IntegrityError Cases

```python
# Database constraint violations (same as current)
user = User(email="duplicate@example.com")
user.create()
# IntegrityError: UNIQUE constraint failed: user.email
```

## ModelForm Integration

**Current:**

```python
if self.instance._state.adding:
    message = "created"
else:
    message = "changed"
self.instance.save(clean_and_validate=False)
```

**New:**

```python
if self.instance._state.adding:
    self.instance.create(clean_and_validate=False)
    message = "created"
else:
    self.instance.persist(clean_and_validate=False)
    message = "changed"
```

Clearer! Explicit methods with correct state tracking.

## Validation Changes

### Uniqueness Validation

**Current** (`base.py:750, 766`):

```python
if f.primary_key and not self._state.adding:
    # Skip pk validation when updating
    continue

if not self._state.adding and model_class_id is not None:
    qs = qs.exclude(id=model_class_id)  # Exclude self
```

**New:**

```python
# In create(): Always validate pk uniqueness (when _state.adding=True)
# In update(): Skip pk validation, exclude self (when _state.adding=False)

# Validation logic continues to use _state.adding for correctness
if f.primary_key and not self._state.adding:
    # Skip pk validation when updating
    continue

if not self._state.adding and model_class_id is not None:
    qs = qs.exclude(id=model_class_id)  # Exclude self
```

**Key:** `_state.adding` remains for validation logic, but `create()`/`persist()` methods make developer intent explicit.

## Critical Implementation Requirements

### 1. Transaction Rollback Guards

**CRITICAL:** Both `create()` and `persist()` MUST wrap all database operations in `transaction.mark_for_rollback_on_error()`.

**Why:** Without this guard, any constraint violation or validation error during the operation would leave the database connection in an error state that requires manual rollback.

**Current code** (`base.py:463`):

```python
def save_base(self, ...):
    with transaction.mark_for_rollback_on_error():
        self._save_table(...)
```

**New code must preserve this:**

```python
def create(self, ...):
    with transaction.mark_for_rollback_on_error():
        self._prepare_related_fields_for_save("create")
        if clean_and_validate:
            self.full_clean()
        self._insert()

def persist(self, ...):
    with transaction.mark_for_rollback_on_error():
        self._prepare_related_fields_for_save("persist", field_objects)
        if clean_and_validate:
            self.full_clean(...)
        self._do_update(update_fields)
```

### 2. Field Objects vs Field Names

**CRITICAL:** `_prepare_related_fields_for_save()` expects Field objects, not field name strings.

**Why:** The method checks `if fields and field not in fields` (`base.py:593`), which requires Field objects for the `in` operator to work correctly.

**Issue in proposal:** `persist()` builds `update_fields` as a set of strings but passes it directly to `_prepare_related_fields_for_save()`, which would break related field validation.

**Solution:** Convert field names to Field objects before passing:

```python
field_objects = None
if update_fields:
    field_objects = [
        self._model_meta.get_field(name) for name in update_fields
    ]
self._prepare_related_fields_for_save("persist", field_objects)
```

### 3. QuerySet Method Safety Features

**CRITICAL:** `get_or_create()` and `update_or_create()` have complex safety logic that MUST be preserved.

**get_or_create() safety features** (`query.py:848-880`):

1. **Atomic transaction** - wraps create in `transaction.atomic()` (line 865)
2. **Callable resolution** - calls `resolve_callables(params)` (line 866)
3. **IntegrityError retry** - catches race conditions and retries GET (lines 868-880)

**update_or_create() safety features** (`query.py:882-927`):

1. **Outer atomic transaction** - wraps entire operation (line 901)
2. **Row locking** - uses `select_for_update()` (line 904)
3. **Callable resolution** - calls `resolve_callables(update_defaults)` (line 909)
4. **Auto-add auto_now fields** - adds fields with custom `pre_save()` to update_fields (lines 916-926)

**Why this matters:**

- Without atomic: Race conditions cause duplicate creates
- Without locking: Concurrent updates can be lost
- Without callable resolution: Lambda/function defaults never execute
- Without auto_now handling: `auto_now` fields don't update

**The proposal's simplified implementations MUST preserve all these features.**

## Implementation Checklist

### Phase 1: Add New Methods (Non-Breaking)

- [ ] Add `Model.create()` method
    - **MUST** wrap in `transaction.mark_for_rollback_on_error()`
    - **MUST** set `_state.adding = False` after successful INSERT
    - **MUST** call `_prepare_related_fields_for_save("create")`
- [ ] Add `Model.persist()` method
    - **MUST** wrap in `transaction.mark_for_rollback_on_error()`
    - **MUST** convert `update_fields` strings to Field objects before passing to `_prepare_related_fields_for_save()`
    - **MUST** call `_prepare_related_fields_for_save("persist", field_objects)`
- [ ] Add `Model._insert()` helper (extracted from `_save_table()`)
- [ ] Add `Model._do_update()` helper (refactored from `_save_table()`)
- [ ] Add `Model._get_fields_for_update()` helper (auto-detect fields with `pre_save()`)
- [ ] Update `_prepare_related_fields_for_save()` to accept operation name (already supports it)
- [ ] Update validation methods to work with explicit operations (minimal changes needed)

### Phase 2: Update QuerySet Methods

- [ ] Update `QuerySet.get_or_create()` to use `obj.create()`
    - **MUST** preserve `transaction.atomic()` wrapper
    - **MUST** preserve `resolve_callables()` for defaults
    - **MUST** preserve IntegrityError/ValidationError retry logic
    - **MUST** set `self._for_write = True`
- [ ] Update `QuerySet.update_or_create()` to use `obj.persist()`
    - **MUST** preserve outer `transaction.atomic()` wrapper
    - **MUST** preserve `select_for_update()` row locking
    - **MUST** preserve `resolve_callables()` for defaults
    - **MUST** preserve auto-adding fields with custom `pre_save()` to update_fields
    - **MUST** set `self._for_write = True`

### Phase 3: Update Related Managers

**Critical:** Related managers must be updated to use instance methods while preserving FK auto-population.

- [ ] Update `ReverseManyToOneManager.create()` to use `instance.create()`
    - File: `plain-models/plain/models/fields/related_managers.py:193-196`
    - Must preserve: FK auto-injection via `kwargs[self.field.name] = self.instance`
- [ ] Update `ReverseManyToOneManager.get_or_create()` to use `instance.create()`
    - File: `plain-models/plain/models/fields/related_managers.py:198-201`
- [ ] Update `ReverseManyToOneManager.update_or_create()` to use `instance.persist()`
    - File: `plain-models/plain/models/fields/related_managers.py:203-206`
- [ ] Update `BaseManyToManyManager.create()` to use `instance.create()`
    - File: `plain-models/plain/models/fields/related_managers.py:418-423`
    - Must preserve: Auto-adding relationship after creation
- [ ] Update `BaseManyToManyManager.get_or_create()` to use `instance.create()`
    - File: `plain-models/plain/models/fields/related_managers.py:425-433`
- [ ] Update `BaseManyToManyManager.update_or_create()` to use `instance.persist()`
    - File: `plain-models/plain/models/fields/related_managers.py:435-443`

### Phase 4: Update Other Internal Usage

- [ ] Update `ModelForm.save()` to use explicit methods
- [ ] Update all internal code using `.save()` to use `.create()` or `.update()`

### Phase 5: Remove Old Code

- [ ] Remove `Model.save()` method (or deprecate with warning)
- [ ] Remove `force_insert` and `force_update` parameters
- [ ] **Keep `_state.adding`** for correctness (tracks persistence state)
- [ ] **Keep `QuerySet.create()`** for internal use (MigrationRecorder, related managers) - or update all internal usages
- [ ] Remove `QuerySet._for_write` attribute (dead code, never read)
- [ ] Update error messages to reference new methods

### Phase 6: Testing

- [ ] Test create() with various field types
- [ ] Test persist() with deferred fields
- [ ] Test persist() with explicit update_fields
- [ ] Test persist() when object deleted (0 rows affected)
- [ ] Test validation in both create() and persist()
- [ ] Test related field validation
- [ ] Test auto_now and auto_now_add fields
- [ ] Test ModelForm integration
- [ ] Test get_or_create() / update_or_create()
- [ ] **Test related manager FK auto-population** (`parent.children.create()`)
- [ ] **Test related manager get_or_create()** (`parent.children.get_or_create()`)
- [ ] **Test related manager update_or_create()** (`parent.children.update_or_create()`)
- [ ] **Test M2M manager create()** (`obj.m2m_field.create()`)
- [ ] **Test M2M manager get_or_create()** (`obj.m2m_field.get_or_create()`)
- [ ] **Test M2M manager update_or_create()** (`obj.m2m_field.update_or_create()`)

## Benefits vs Current Approach

| Aspect             | Current `save()`                   | Explicit `create()`/`persist()`                |
| ------------------ | ---------------------------------- | ---------------------------------------------- |
| **Intent**         | Ambiguous                          | Explicit                                       |
| **Queries**        | Try UPDATE then INSERT             | Direct INSERT or UPDATE                        |
| **State tracking** | `_state.adding` (implicit)         | `_state.adding` + explicit methods             |
| **Edge cases**     | Auto-detected, can be surprising   | Explicit call + state validation               |
| **Validation**     | Same for both ops                  | Can differ by operation                        |
| **Error messages** | Generic "save()"                   | Specific "create()" or "persist()"             |
| **Return value**   | None                               | Self (both - chainable)                        |
| **Testability**    | Hard to verify operation type      | Easy: mock create/persist separately           |
| **Code clarity**   | `obj.save()` - creating? updating? | `obj.create()` or `obj.persist()` - obvious    |
| **API ambiguity**  | One method, two behaviors          | Two methods, distinct from `QuerySet.update()` |

## Backwards Compatibility

**Breaking changes:**

- Remove `Model.save()` method
- Remove `force_insert` and `force_update` parameters
- `QuerySet.create()` marked as internal/discouraged (but kept for compatibility)

**Migration path:**

1. Deprecation warning in `save()` pointing to new methods
2. Add new methods in v1.x
3. Update all examples and docs
4. Remove `save()` in v2.0

**For users:**

```python
# Old code
user = User(email="test@example.com")
user.save()

# New code
user = User(email="test@example.com")
user.create()  # Explicit!
```

Search and replace is mostly mechanical:

- `obj.save(force_insert=True)` → `obj.create()`
- `obj.save()` → `obj.create()` or `obj.save_changes()` (need to determine from context using `_state.adding`)
- `Model.query.create(**kwargs)` → prefer `Model(**kwargs).create()` but old syntax still works (marked as internal)

## Open Questions

### 1. Should `create()` return `self` or `None`?

**Option A: Return `self`** (proposed)

```python
user = User(email="test@example.com").create()
```

✅ Enables chaining
✅ More ergonomic
❌ Different from current `save()` (returns None)

**Option B: Return `None`**

```python
user = User(email="test@example.com")
user.create()
```

✅ Consistent with current `save()`
❌ Less ergonomic
❌ Misses opportunity for improvement

**Recommendation:** Return `self`. It's a breaking change anyway, might as well improve the API.

### 2. Should we keep `QuerySet.create()` as a convenience?

**Recommendation:** Keep it for internal use, but discourage in user code.

`QuerySet.create()` is still used by:

- `MigrationRecorder` (migrations/recorder.py:109)
- Related managers (if not updated)

**Options:**

1. **Keep as internal API** - mark as "internal" or "discouraged" in docs, delegate to `instance.create()`
2. **Remove entirely** - update MigrationRecorder and all related managers

**Decision:** Keep for backwards compatibility and smoother migration. Users should prefer `Model(...).create()` but internal code can continue using `QuerySet.create()`.

See "Why Remove QuerySet.create() But Keep get_or_create()?" section above for detailed reasoning on MigrationRecorder usage.

### 3. What about `bulk_create()` and `bulk_update()`?

These are **bulk operations** - fundamentally different from instance methods. They:

- Don't instantiate models (for performance)
- Skip validation
- Return lists, not instances

**Recommendation:** Keep them as-is. They serve a different purpose.

### 4. Should `update()` do anything special if 0 rows affected?

When an object is updated but 0 rows are affected (usually because another process deleted it):

**Option A: Silent success, return self** (proposed)

```python
user.update(email="new@example.com")  # Returns self even if 0 rows
```

✅ Simple, consistent return value
✅ Concurrent deletion is rare edge case
✅ User can refresh_from_db() if they care
❌ Silently "succeeds" even if object deleted

**Option B: Raise error if 0 rows**

```python
user.update()  # Raises DatabaseError if object deleted
```

✅ Can't silently fail
❌ Might not always be an error
❌ Inconsistent with QuerySet.update() behavior

**Option C: Check database and sync state**

```python
user.update()  # Detects deletion and updates internal state
```

✅ Most correct
❌ Extra query overhead
❌ Complex implementation

**Recommendation:** Option A (silent success). Matches current `save()` behavior and keeps the API simple. Users who care about concurrent deletion can implement their own checks.

## Related Work

### Django

Django has debated this but kept `save()` for backwards compatibility. They provide:

- `save(force_insert=True)` and `save(force_update=True)` parameters
- `QuerySet.create()` as convenience
- Same UPDATE-then-INSERT pattern

**Why they kept it:** Massive ecosystem, breaking change cost too high.

**Why Plain can change:** Smaller ecosystem, values explicitness, still pre-1.0.

### Rails (ActiveRecord)

Rails has explicit methods:

- `record.save` - smart save (like Plain's current)
- `record.save!` - save or raise
- `Model.create` - class method for create
- `record.update` - instance method for update

**Difference:** Rails `update` takes attributes as arguments, Plain would use setters.

### SQLAlchemy

SQLAlchemy uses explicit session:

- `session.add(obj)` - mark for insert
- `session.commit()` - persist changes
- Very explicit, but more verbose

**Difference:** Plain's approach is simpler - no session tracking.

## Summary

Replacing `save()` with explicit `create()` and `save_changes()` methods:

✅ **Clearer intent** - code explicitly states operation
✅ **Better performance** - direct INSERT/UPDATE, no try-then-fallback
✅ **Simpler validation** - operation-specific logic
✅ **Better errors** - specific to create vs update
✅ **Chainable methods** - both return self for method chaining
✅ **Easier testing** - mock create/update separately
✅ **Code cleanup** - removes dead code (`QuerySet._for_write`)
✅ **Related managers preserved** - FK auto-population still works
✅ **Correct state tracking** - keeps `_state.adding` for validation and related managers

❌ **Breaking change** - all `save()` calls need updating
❌ **Migration effort** - search and replace across codebase
❌ **Related manager updates required** - 6 methods in `related_managers.py`
❌ **Still need `_state.adding`** - can't eliminate internal state tracking

**Recommendation:** Implement this change. Plain values explicitness and clarity. The explicit methods make developer intent clear while `_state.adding` ensures correctness.

**CRITICAL CAUTION:** This change requires careful implementation of transaction safety, field object handling, and QuerySet method preservation. Review the "Critical Implementation Requirements" section before implementing. Failure to preserve these safety features will cause data corruption, connection poisoning, and race conditions in production.

## Files Requiring Changes

### Core Implementation

- **`plain-models/plain/models/base.py`**
    - Import `transaction` module if not already imported
    - Add `Model.create()` method
        - Wrap in `transaction.mark_for_rollback_on_error()`
        - Set `_state.adding = False` after successful INSERT
    - Add `Model.save_changes()` method
        - Wrap in `transaction.mark_for_rollback_on_error()`
        - Check `_state.adding` is False
        - Convert field name strings to Field objects for related field validation
    - Add `Model._insert()` helper (extract from `_save_table()`)
    - Refactor `_save_table()` into `_do_update()` helper
    - Update validation methods (keep `_state.adding` checks for correctness)
    - Remove/deprecate `save()`, `save_base()`, `_save_table()`
    - **Keep `_state.adding`** - still needed for validation and related managers

### QuerySet Changes

- **`plain-models/plain/models/query.py`**
    - Update `get_or_create()` to use `instance.create()` (line 848)
        - **CRITICAL:** Preserve `transaction.atomic()` wrapper (line 865)
        - **CRITICAL:** Preserve `resolve_callables()` (line 866)
        - **CRITICAL:** Preserve IntegrityError retry logic (lines 868-880)
    - Update `update_or_create()` to use `instance.save_changes()` (line 882)
        - **CRITICAL:** Preserve outer `transaction.atomic()` (line 901)
        - **CRITICAL:** Preserve `select_for_update()` locking (line 904)
        - **CRITICAL:** Preserve `resolve_callables()` (line 909)
        - **CRITICAL:** Preserve auto_now field addition to update_fields (lines 916-926)
    - **Decision needed:** Remove `create()` method (line 641) OR keep for internal use
        - If removed: Must update `MigrationRecorder` and related managers
        - If kept: Mark as internal, delegate to `Model(**kwargs).create()`
    - Remove `_for_write` attribute references (dead code)

### Related Managers

- **`plain-models/plain/models/fields/related_managers.py`**
    - Update `ReverseManyToOneManager.create()` (line 193)
    - Update `ReverseManyToOneManager.get_or_create()` (line 198)
    - Update `ReverseManyToOneManager.update_or_create()` (line 203)
    - Update `BaseManyToManyManager.create()` (line 418)
    - Update `BaseManyToManyManager.get_or_create()` (line 425)
    - Update `BaseManyToManyManager.update_or_create()` (line 435)

### Form Integration

- **`plain-models/plain/models/forms.py`**
    - Update `ModelForm.save()` to use explicit methods (line 395)

### Validation

- **`plain-models/plain/models/constraints.py`**
    - **Keep `_state.adding` checks** (line 410) - needed for excluding self from constraint validation

### Tests

- **`plain-models/tests/test_related_manager_api.py`**
    - Verify `parent.children.create()` still auto-populates FK
    - Add tests for all related manager methods

### Example Code

- **All files in `example/` directory**
    - Update any `.save()` calls to `.create()` or `.save_changes()`

### Documentation

- **All README.md files in plain-models/**
    - Update examples to use `.create()` and `.save_changes()`
    - Remove references to `.save()`, `force_insert`, `force_update`
    - Add note distinguishing `instance.save_changes()` from `QuerySet.update()`
