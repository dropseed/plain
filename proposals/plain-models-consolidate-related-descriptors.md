# plain-models: Consolidate Related Field Descriptors

**Remove descriptor indirection by making ForeignKeyField and ManyToManyField act as their own descriptors.**

## Problem

`ForeignKey` and `ManyToManyField` use separate descriptor classes (`ForwardForeignKeyDescriptor` and `ForwardManyToManyDescriptor`) in `related_descriptors.py` that act as thin wrappers with no independent logic. This creates:

- Unnecessary indirection through wrapper classes
- Split responsibility between field and descriptor
- Extra file to maintain (`related_descriptors.py`)
- Inconsistent pattern (base `Field` acts as its own descriptor)

## Solution

Make `ForeignKey` and `ManyToManyField` implement the descriptor protocol directly by adding `__get__` and `__set__` methods to the field classes themselves.

## Benefits

- **Better encapsulation** - All FK/M2M behavior in one place
- **Less indirection** - Direct method calls, simpler stack traces
- **Fewer abstractions** - Removes 2 descriptor classes and `related_descriptors.py` (310 lines)
- **Consistent pattern** - Matches base `Field` behavior
- **Net reduction** - 69 fewer lines overall

## Changes

**Modified:** `plain-models/plain/models/fields/related.py` (+241 lines)

- Add `__get__`, `__set__`, `__reduce__` methods to `ForeignKey`
- Add `__get__`, `__set__` methods to `ManyToManyField`
- Add `_ForeignKeyValueDescriptor` helper for FK value access (e.g., `obj.parent_id`)

**Removed:** `plain-models/plain/models/fields/related_descriptors.py` (-310 lines)

**Net:** -69 lines

## Impact

- ✅ Zero breaking changes - all public APIs unchanged
- ✅ All 269 tests pass (including 27 descriptor tests)
- ✅ No external imports of removed file
- ✅ Behavior fully preserved

This is a purely internal refactoring.
