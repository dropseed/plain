# Framework-wide Abstract Base Classes

**Convert base classes with `NotImplementedError` methods to ABC pattern for type safety and earlier error detection across all Plain packages.**

## Problem

Many plugin/extension points across Plain use `raise NotImplementedError(...)` for required methods:

- Errors only discovered at runtime when method called
- No type checker support (Mypy/Pyright can't verify completeness)
- Unclear which methods are required vs optional
- Base classes can be accidentally instantiated

## Solution

Convert to ABC pattern with `@abstractmethod`:

- Errors caught at class definition/import time
- Type checkers verify all abstract methods implemented
- Self-documenting interface contracts
- Prevents base class instantiation

## Classes to Convert

### High Priority (Core interfaces, multiple methods)

**BaseConstraint** (4 abstract methods)

- Location: `plain-models/plain/models/constraints.py:18`
- Methods: `constraint_sql()`, `create_sql()`, `remove_sql()`, `validate()`

**BasePasswordHasher** (4 abstract methods)

- Location: `plain-passwords/plain/passwords/hashers.py:161`
- Methods: `verify()`, `encode()`, `decode()`, `safe_summary()`
- Security-critical interface

**OAuthProvider** (3 abstract methods)

- Location: `plain-oauth/plain/oauth/providers.py:51`
- Methods: `refresh_oauth_token()`, `get_oauth_token()`, `get_oauth_user()`

**Operation** (2 abstract methods)

- Location: `plain-models/plain/models/migrations/operations/base.py:11`
- Methods: `state_forwards()`, `database_forwards()`
- Core migration system

### Medium Priority (Plugin patterns)

**BaseEmailBackend** (1 abstract method)

- Location: `plain-email/plain/email/backends/base.py:13`
- Method: `send_messages()`

**Worker** (1 abstract method)

- Location: `plain/plain/server/workers/base.py:51`
- Method: `run()`

**Flag** (2 abstract methods)

- Location: `plain-flags/plain/flags/flags.py:24`
- Methods: `get_key()`, `get_value()`

**BaseSerializer** (1 abstract method)

- Location: `plain-models/plain/models/migrations/serializer.py:26`
- Method: `serialize()`
- 30+ subclass implementations

**BaseSequenceSerializer** (1 abstract method)

- Location: `plain-models/plain/models/migrations/serializer.py:36`
- Method: `_format()`

### Lower Priority (Smaller interfaces)

**FieldCacheMixin** - `get_cache_name()`
**Reference** (DDL) - `__str__()`
**ChartCard** - `get_chart_data()`
**ReverseRelatedObjectDescriptor** - 2 methods
**BaseDatabaseClient** - `settings_to_cmd_args_env()`

### Database Backend Classes

See separate proposal: `plain-models-database-abstract-base-classes.md`

- BaseDatabaseIntrospection (5 methods)
- BaseDatabaseWrapper (6 methods)
- Plus others

## Already Using ABC

**PreflightCheck** - `plain/plain/preflight/checks.py:6`
**Audit** - `plain-scan/plain/scan/audits/base.py:11`

Good examples to follow!

## Completed

**FileUploadHandler** - `plain/plain/internal/files/uploadhandler.py:81` ✅

- Converted 2 abstract methods: `receive_data_chunk()`, `file_complete()`
- All tests passing, type checking passes

## Implementation

For each class:

1. Add `from abc import ABC, abstractmethod`
2. Inherit from `ABC`
3. Replace `raise NotImplementedError(...)` with `@abstractmethod` and `...`
4. Add type annotations
5. Keep all default implementations unchanged
6. Verify all subclasses still work

## Statistics

- **14 strong candidates**
- **36+ abstract methods** total
- **8 packages** affected: plain-models, plain-oauth, plain-email, plain-passwords, plain-admin, plain-flags, plain, plain-scan

## Benefits

- Import-time vs runtime errors
- Full type checker support
- Prevents base class instantiation
- Better IDE autocomplete
- Explicit interface contracts
- Clearer framework architecture
