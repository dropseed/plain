# Remove Index auto-naming

Done. Removed `set_name_with_model` and the auto-naming machinery from `Index`. Since `Index.__init__` requires `name` and `deconstruct()` always includes it, the `if not index.name` branches in `meta.py` and `options.py` were dead code.
