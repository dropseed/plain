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

from .. import util

PLATFORM = platform.system()
IS_CYGWIN = PLATFORM.startswith("CYGWIN")


class WorkerTmp:
    def __init__(self, cfg):
        fd, name = tempfile.mkstemp(prefix="wgunicorn-")

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

    def notify(self):
        new_time = time.monotonic()
        os.utime(self._tmp.fileno(), (new_time, new_time))

    def last_update(self):
        return os.fstat(self._tmp.fileno()).st_mtime

    def fileno(self):
        return self._tmp.fileno()

    def close(self):
        return self._tmp.close()
