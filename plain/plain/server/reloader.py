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

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.daemon = True
        self._callback = callback

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

    def should_reload(self, file_path: str) -> bool:
        """Check if a file change should trigger a reload."""
        filename = os.path.basename(file_path)

        # Watch .py files
        if file_path.endswith(".py"):
            return True

        # Watch .env* files
        if filename.startswith(".env"):
            return True

        return False

    def run(self) -> None:
        """Watch for file changes and trigger callback."""
        watch_paths = self.get_watch_paths()

        for changes in watchfiles.watch(*watch_paths, rust_timeout=1000):
            for change_type, file_path in changes:
                # Only reload on modify and create events
                if change_type in (watchfiles.Change.modified, watchfiles.Change.added):
                    if self.should_reload(file_path):
                        self._callback(file_path)
