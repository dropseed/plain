from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import os
import os.path
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable

COMPILED_EXT_RE = re.compile(r"py[co]$")


class Reloader(threading.Thread):
    def __init__(
        self,
        extra_files: Iterable[str] | None = None,
        interval: int = 1,
        callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.daemon = True
        self._extra_files: set[str] = set(extra_files or ())
        self._interval = interval
        self._callback = callback

    def add_extra_file(self, filename: str) -> None:
        self._extra_files.add(filename)

    def get_files(self) -> list[str]:
        fnames = [
            COMPILED_EXT_RE.sub("py", module.__file__)  # type: ignore[arg-type]
            for module in tuple(sys.modules.values())
            if getattr(module, "__file__", None)
        ]

        fnames.extend(self._extra_files)

        return fnames

    def run(self) -> None:
        mtimes: dict[str, float] = {}
        while True:
            for filename in self.get_files():
                try:
                    mtime = os.stat(filename).st_mtime
                except OSError:
                    continue
                old_time = mtimes.get(filename)
                if old_time is None:
                    mtimes[filename] = mtime
                    continue
                elif mtime > old_time:
                    if self._callback:
                        self._callback(filename)
            time.sleep(self._interval)


has_inotify = False
if sys.platform.startswith("linux"):
    try:
        import inotify.constants
        from inotify.adapters import Inotify

        has_inotify = True
    except ImportError:
        pass


if has_inotify:

    class InotifyReloader(threading.Thread):
        event_mask = (
            inotify.constants.IN_CREATE
            | inotify.constants.IN_DELETE
            | inotify.constants.IN_DELETE_SELF
            | inotify.constants.IN_MODIFY
            | inotify.constants.IN_MOVE_SELF
            | inotify.constants.IN_MOVED_FROM
            | inotify.constants.IN_MOVED_TO
        )

        def __init__(
            self,
            extra_files: Iterable[str] | None = None,
            callback: Callable[[str], None] | None = None,
        ) -> None:
            super().__init__()
            self.daemon = True
            self._callback = callback
            self._dirs: set[str] = set()
            self._watcher = Inotify()

            if extra_files:
                for extra_file in extra_files:
                    self.add_extra_file(extra_file)

        def add_extra_file(self, filename: str) -> None:
            dirname = os.path.dirname(filename)

            if dirname in self._dirs:
                return None

            self._watcher.add_watch(dirname, mask=self.event_mask)
            self._dirs.add(dirname)

        def get_dirs(self) -> set[str]:
            fnames = [
                os.path.dirname(
                    os.path.abspath(COMPILED_EXT_RE.sub("py", module.__file__))  # type: ignore[arg-type]
                )
                for module in tuple(sys.modules.values())
                if getattr(module, "__file__", None)
            ]

            return set(fnames)

        def run(self) -> None:
            self._dirs = self.get_dirs()

            for dirname in self._dirs:
                if os.path.isdir(dirname):
                    self._watcher.add_watch(dirname, mask=self.event_mask)

            for event in self._watcher.event_gen():  # type: ignore[attr-defined]
                if event is None:
                    continue

                filename = event[3]  # type: ignore[index]

                self._callback(filename)  # type: ignore[misc]

else:

    class InotifyReloader:
        def __init__(
            self,
            extra_files: Iterable[str] | None = None,
            callback: Callable[[str], None] | None = None,
        ) -> None:
            raise ImportError(
                "You must have the inotify module installed to use the inotify reloader"
            )


preferred_reloader = InotifyReloader if has_inotify else Reloader

reloader_engines = {
    "auto": preferred_reloader,
    "poll": Reloader,
    "inotify": InotifyReloader,
}
