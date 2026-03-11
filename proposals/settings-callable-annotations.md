# Support Callable type annotations in settings

## Problem

`_load_module_settings` reads raw `__annotations__` from modules, which are strings under `from __future__ import annotations`. This means type annotations like `Callable | None` are stored as the string `'Callable | None'` rather than resolved types, causing `_is_instance_of_type` to raise `ValueError: Unsupported type hint`.

Two fixes needed:

1. **`_load_module_settings`** should use `typing.get_type_hints()` instead of raw `__annotations__` to resolve string annotations.
2. **`_is_instance_of_type`** should handle `Callable` types (check with `callable(value)`).

## Impact

Currently you can't add type annotations to callable settings in `default_settings.py` (e.g., `ADMIN_HAS_PERMISSION: Callable | None = None`). The workaround is to omit the annotation.
