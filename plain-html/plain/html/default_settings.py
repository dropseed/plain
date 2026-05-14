# Override the on-disk compile cache location. An empty / `None` value
# keeps the default at `<project>/.plain/html/` (alongside
# `.plain/assets/compiled`, `.plain/dev/logs`, etc.). Also settable via
# the `PLAIN_HTML_CACHE_DIR` environment variable.
HTML_CACHE_DIR: str | None = None
# Disable the on-disk compile cache entirely. With caching off, every render
# re-emits Python source in-memory — useful in CI or read-only sandboxes
# where writing to `.plain/html/` isn't viable. Also settable via the
# `PLAIN_HTML_CACHE_DISABLED` environment variable.
HTML_CACHE_DISABLED: bool = False
