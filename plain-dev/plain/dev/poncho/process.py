import datetime
import os
import signal
import subprocess
import threading
from queue import Queue
from typing import Any

from .compat import ON_WINDOWS
from .printer import Message


class Process:
    """
    A simple utility wrapper around a subprocess.Popen that stores
    a number of attributes needed by Poncho and supports forwarding process
    lifecycle events and output to a queue.
    """

    def __init__(
        self,
        cmd: str,
        name: str | None = None,
        color: str | None = None,
        quiet: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.cmd = cmd
        self.color = color
        self.quiet = quiet
        self.name = name
        self.env = os.environ.copy() if env is None else env
        self.cwd = cwd

        self._clock = datetime.datetime
        self._child = None
        self._child_ctor = Popen

    def run(
        self, events: Queue[Message] | None = None, ignore_signals: bool = False
    ) -> None:
        self._events = events
        self._child = self._child_ctor(self.cmd, env=self.env, cwd=self.cwd)
        self._send_message({"pid": self._child.pid}, type="start")

        # Don't pay attention to SIGINT/SIGTERM. The process itself is
        # considered unkillable, and will only exit when its child (the shell
        # running the Procfile process) exits.
        if ignore_signals:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)

        # Read stdout and stderr concurrently using threads
        stdout_thread = threading.Thread(
            target=self._read_stream, args=(self._child.stdout, "stdout")
        )
        stderr_thread = threading.Thread(
            target=self._read_stream, args=(self._child.stderr, "stderr")
        )

        stdout_thread.start()
        stderr_thread.start()

        # Wait for both threads to complete
        stdout_thread.join()
        stderr_thread.join()

        self._child.wait()

        self._send_message({"returncode": self._child.returncode}, type="stop")

    def _read_stream(self, stream: Any, stream_name: str) -> None:
        """Read lines from a stream and send them as messages."""
        for line in iter(stream.readline, b""):
            if not self.quiet:
                self._send_message(line, stream=stream_name)
        stream.close()

    def _send_message(
        self, data: bytes | dict[str, Any], type: str = "line", stream: str = "stdout"
    ) -> None:
        if self._events is not None:
            self._events.put(
                Message(
                    type=type,
                    data=data,
                    time=self._clock.now(),
                    name=self.name,
                    color=self.color,
                    stream=stream,
                )
            )


class Popen(subprocess.Popen):
    def __init__(self, cmd: str, **kwargs: Any) -> None:
        start_new_session = kwargs.pop("start_new_session", True)
        options = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": True,
            "close_fds": not ON_WINDOWS,
        }
        options.update(**kwargs)

        if ON_WINDOWS:
            # MSDN reference:
            #   http://msdn.microsoft.com/en-us/library/windows/desktop/ms684863%28v=vs.85%29.aspx
            create_no_window = 0x08000000
            options.update(creationflags=create_no_window)
        elif start_new_session:
            options.update(start_new_session=True)

        super().__init__(cmd, **options)
