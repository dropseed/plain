from __future__ import annotations

import os
import os.path
import re
import sys
import threading
from collections.abc import Callable

import watchfiles

COMPILED_EXT_RE = re.compile(r"py[co]$")


class Reloader(threading.Thread):
    """File change reloader using watchfiles for cross-platform native file watching."""

    def __init__(self, callback: Callable[[str], None], watch_html: bool) -> None:
        super().__init__()
        self.daemon = True
        self._callback = callback
        self._watch_html = watch_html

    def get_watch_paths(self) -> set[str]:
        """Get all directories to watch for changes."""
        paths = set()

        # Get directories from loaded Python modules
        for module in tuple(sys.modules.values()):
            if not hasattr(module, "__file__") or not module.__file__:
                continue
            # Convert .pyc/.pyo to .py and get directory
            file_path = COMPILED_EXT_RE.sub("py", module.__file__)
            dir_path = os.path.dirname(os.path.abspath(file_path))
            if os.path.isdir(dir_path):
                paths.add(dir_path)

        # Add current working directory for .env files
        cwd = os.getcwd()
        if os.path.isdir(cwd):
            paths.add(cwd)

        return paths

    def run(self) -> None:
        """Watch for file changes and trigger callback."""
        watch_paths = self.get_watch_paths()

        for changes in watchfiles.watch(*watch_paths, rust_timeout=1000):
            for change_type, file_path in changes:
                should_reload = False
                filename = os.path.basename(file_path)

                # Python files: reload on modify/add
                if change_type in (watchfiles.Change.modified, watchfiles.Change.added):
                    if file_path.endswith(".py"):
                        should_reload = True

                # .env files: reload on modify/add/delete
                if change_type in (
                    watchfiles.Change.modified,
                    watchfiles.Change.added,
                    watchfiles.Change.deleted,
                ):
                    if filename.startswith(".env"):
                        should_reload = True

                # HTML files: only reload on add/delete (Jinja auto-reloads modifications)
                if self._watch_html and change_type in (
                    watchfiles.Change.added,
                    watchfiles.Change.deleted,
                ):
                    if file_path.endswith(".html"):
                        should_reload = True

                if should_reload:
                    self._callback(file_path)
