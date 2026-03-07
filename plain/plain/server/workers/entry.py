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
    import traceback

    from ..errors import APP_LOAD_ERROR, WORKER_BOOT_ERROR, AppImportError
    from ..sock import TCP6Socket, TCPSocket, UnixSocket

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
        listeners = []
        for raw_sock, addr, family, is_ssl in listener_data:
            sock_class = sock_class_map[family]
            fd = raw_sock.detach()
            listener = sock_class(addr, is_ssl=is_ssl, fd=fd)
            listeners.append(listener)

        # Setup Plain runtime (settings, packages, logging)
        import plain.runtime

        try:
            plain.runtime.setup()
        finally:
            # Always replace bootstrap stderr handler — either with proper
            # logging from setup(), or to avoid handler accumulation on failure.
            log.handlers.clear()
            log.propagate = True

        # Configure access logger based on the --access-log CLI flag.
        access_logger = logging.getLogger("plain.server.access")
        access_logger.setLevel(logging.INFO)
        access_logger.handlers.clear()
        access_logger.propagate = False
        if app.accesslog:
            from plain.logs.configure import create_log_formatter

            log_handler = logging.StreamHandler(sys.stdout)
            log_handler.setFormatter(
                create_log_formatter(plain.runtime.settings.LOG_FORMAT)
            )
            access_logger.addHandler(log_handler)

        # Load the request handler
        try:
            handler = app.load()
        except SyntaxError:
            if not app.reload:
                raise
            log.exception("Error loading application")
            from .. import util

            handler = util.make_fail_handler(traceback.format_exc())

        from .worker import Worker

        worker = Worker(age, os.getppid(), listeners, app, timeout, heartbeat, handler)
        worker.pid = os.getpid()

        log.info("Server worker started pid=%s", worker.pid)
        worker.init_process()
        sys.exit(0)
    except SystemExit:
        raise
    except AppImportError as e:
        log.debug("Exception while loading the application", exc_info=True)
        print(f"{e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(APP_LOAD_ERROR)
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
