#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

import errno
import os
import tempfile


class Pidfile:
    """\
    Manage a PID file. If a specific name is provided
    it and '"%s.oldpid" % name' will be used. Otherwise
    we create a temp file using os.mkstemp.
    """

    def __init__(self, fname: str) -> None:
        self.fname = fname
        self.pid: int | None = None

    def create(self, pid: int) -> None:
        oldpid = self.validate()
        if oldpid:
            if oldpid == os.getpid():
                return None
            msg = "Already running on PID %s (or pid file '%s' is stale)"
            raise RuntimeError(msg % (oldpid, self.fname))

        self.pid = pid

        # Write pidfile
        fdir = os.path.dirname(self.fname)
        if fdir and not os.path.isdir(fdir):
            raise RuntimeError(f"{fdir} doesn't exist. Can't create pidfile.")
        fd, fname = tempfile.mkstemp(dir=fdir)
        os.write(fd, (f"{self.pid}\n").encode())
        if self.fname:
            os.rename(fname, self.fname)
        else:
            self.fname = fname
        os.close(fd)

        # set permissions to -rw-r--r--
        os.chmod(self.fname, 420)
        return None

    def rename(self, path: str) -> None:
        self.unlink()
        self.fname = path
        assert self.pid is not None
        self.create(self.pid)
        return None

    def unlink(self) -> None:
        """delete pidfile"""
        try:
            with open(self.fname) as f:
                pid1 = int(f.read() or 0)

            if pid1 == self.pid:
                os.unlink(self.fname)
        except Exception:
            pass
        return None

    def validate(self) -> int | None:
        """Validate pidfile and make it stale if needed"""
        if not self.fname:
            return None
        try:
            with open(self.fname) as f:
                try:
                    wpid = int(f.read())
                except ValueError:
                    return None

                try:
                    os.kill(wpid, 0)
                    return wpid
                except OSError as e:
                    if e.args[0] == errno.EPERM:
                        return wpid
                    if e.args[0] == errno.ESRCH:
                        return None
                    raise
        except OSError as e:
            if e.args[0] == errno.ENOENT:
                return None
            raise
