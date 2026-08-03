from __future__ import annotations

import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import ServerApplication
    from .workertmp import WorkerHeartbeat


def worker_main(
    age: int,
    listener_data: list[
        tuple[socket.socket, tuple[str, int] | str, socket.AddressFamily, bool]
    ],
    app: ServerApplication,
    timeout: float,
    heartbeat: WorkerHeartbeat,
) -> None:
    """Entry point for spawned worker processes.

    All Plain imports are inside this function because the spawned process
    re-imports the module BEFORE this function runs. Any module-level import
    that triggers model registration or settings access will fail because
    setup() hasn't been called yet. Same pattern as plain-jobs
    _worker_process_initializer.
    """
    import logging
    import os
    import sys
    import time
    import traceback

    from ..errors import WORKER_BOOT_ERROR
    from ..sock import BaseSocket, TCP6Socket, TCPSocket, UnixSocket

    # Temporary stderr handler for the brief window before
    # runtime.setup() configures proper logging.
    log = logging.getLogger("plain.server")
    log.setLevel(logging.INFO)
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(_handler)

    worker = None

    try:
        sock_class_map = {
            socket.AF_INET: TCPSocket,
            socket.AF_INET6: TCP6Socket,
            socket.AF_UNIX: UnixSocket,
        }

        # Reconstruct BaseSocket wrappers from raw socket objects.
        # multiprocessing passes socket.socket objects via pickle/SCM_RIGHTS.
        # detach() releases the FD from the raw socket object so it won't
        # double-close when BaseSocket.__init__(fd=...) calls os.close(fd)
        # after socket.fromfd() dups it.
        listeners: list[BaseSocket] = []
        for raw_sock, addr, family, is_ssl in listener_data:
            sock_class = sock_class_map[family]
            fd = raw_sock.detach()
            listener = sock_class(addr, is_ssl=is_ssl, fd=fd)  # ty: ignore[invalid-argument-type]
            listeners.append(listener)

        import plain.runtime

        # Importing and loading app code — the phases a mid-edit save can
        # transiently break. In reload mode a failure here must not exit
        # with a boot error code (that halts the arbiter, and the whole
        # dev stack with it) — the traceback is served instead, until the
        # next file change recycles this process with fresh imports.
        boot_failure_traceback = None
        try:
            # Setup Plain runtime (settings, packages, logging)
            try:
                plain.runtime.setup()
            finally:
                # Always replace bootstrap stderr handler — either with proper
                # logging from setup(), or to avoid handler accumulation on failure.
                log.handlers.clear()
                log.propagate = True

            # Configure access logger based on the --access-log CLI flag.
            from ..accesslog import configure_access_log

            configure_access_log(
                enabled=app.accesslog,
                log_format=plain.runtime.settings.LOG_FORMAT,
            )

            # Load the request handler
            handler = app.load()
        except Exception:
            if not app.reload:
                raise
            log.exception(
                "Worker failed to boot, serving the error until the code changes"
            )
            boot_failure_traceback = traceback.format_exc()

        if boot_failure_traceback is not None:
            # Served outside the except block so the failed boot's frames
            # aren't kept alive for the lifetime of the stand-in server.
            from .boot_failure import serve_boot_failure

            try:
                serve_boot_failure(
                    listeners=listeners,
                    app=app,
                    heartbeat=heartbeat,
                    traceback_text=boot_failure_traceback,
                )
            except Exception:
                # The stand-in must not become a new way to halt the dev
                # stack — log it and recycle, pausing so repeated crashes
                # don't respawn in a tight loop.
                log.exception("Boot failure server crashed")
                time.sleep(5)
            sys.exit(0)

        from .worker import Worker

        worker = Worker(age, os.getppid(), listeners, app, timeout, heartbeat, handler)
        worker.pid = os.getpid()

        log.info("Server worker started (pid: %s)", worker.pid)
        worker.init_process()
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        log.exception("Exception in worker process")
        if worker is None or not worker.booted:
            sys.exit(WORKER_BOOT_ERROR)
        sys.exit(-1)
    finally:
        log.info("Server worker exiting (pid: %s)", os.getpid())
        try:
            heartbeat.close()
        except Exception:
            log.warning("Exception during worker exit:\n%s", traceback.format_exc())
