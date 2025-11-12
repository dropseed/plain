# plain-models: Database Backend Abstract Base Classes

**Convert database backend base classes with `NotImplementedError` methods to ABC pattern for type safety and earlier error detection.**

## Problem

Backend base classes use `raise NotImplementedError(...)` for required methods, which means:

- Errors only discovered at runtime when method called
- No type checker support (Mypy/Pyright can't verify completeness)
- Unclear which methods are required vs optional

## Solution

Convert to ABC pattern with `@abstractmethod`:

- Errors caught at class definition/import time
- Type checkers verify all abstract methods implemented
- Self-documenting - clearly shows required interface

## Classes to Convert

### Strong Candidates

**BaseDatabaseClient** (1 abstract method)

- `settings_to_cmd_args_env()`

**BaseDatabaseIntrospection** (5 abstract methods)

- `get_table_list()`, `get_table_description()`, `get_sequences()`, `get_relations()`, `get_constraints()`

**BaseDatabaseWrapper** (6 abstract methods)

- `get_database_version()`, `get_connection_params()`, `get_new_connection()`, `create_cursor()`, `_set_autocommit()`, `is_usable()`

### Do NOT Convert

**BaseDatabaseFeatures** - Feature flags/attributes, no required methods

**BaseDatabaseCreation** - Template pattern with working defaults

**BaseDatabaseValidation** - No required methods, optional overrides only

## Implementation

For each class:

1. Add `from abc import ABC, abstractmethod`
2. Inherit from `ABC`
3. Replace `raise NotImplementedError(...)` with `@abstractmethod` and `...`
4. Add type annotations while there
5. Keep all default implementations unchanged
6. Verify all backends (MySQL, PostgreSQL, SQLite) still work

## Benefits

- Import-time vs runtime errors
- Type checker support
- Prevents base class instantiation
- Better IDE autocomplete
- Explicit contracts
