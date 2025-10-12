from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import os
import platform
import tempfile
import time
from typing import TYPE_CHECKING

from .. import util

if TYPE_CHECKING:
    from ..config import Config

PLATFORM = platform.system()
IS_CYGWIN = PLATFORM.startswith("CYGWIN")


class WorkerTmp:
    def __init__(self, cfg: Config) -> None:
        fd, name = tempfile.mkstemp(prefix="wplain-")

        # unlink the file so we don't leak temporary files
        try:
            if not IS_CYGWIN:
                util.unlink(name)
            # In Python 3.8, open() emits RuntimeWarning if buffering=1 for binary mode.
            # Because we never write to this file, pass 0 to switch buffering off.
            self._tmp = os.fdopen(fd, "w+b", 0)
        except Exception:
            os.close(fd)
            raise

    def notify(self) -> None:
        new_time = time.monotonic()
        os.utime(self._tmp.fileno(), (new_time, new_time))

    def last_update(self) -> float:
        return os.fstat(self._tmp.fileno()).st_mtime

    def fileno(self) -> int:
        return self._tmp.fileno()

    def close(self) -> None:
        return self._tmp.close()
