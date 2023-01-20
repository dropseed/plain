# forge-core

All Forge packages should depend on `forge-core`.

It provides the following:

- the `forge` CLI (autodiscovers `forge-x` commands)
- default Django `manage.py`, `wsgi.py`, and `asgi.py` files
- the `Forge` class with path, tmp, and executable utils
