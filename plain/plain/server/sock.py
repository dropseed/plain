from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import errno
import logging
import os
import socket
import ssl
import stat
import sys
import time
from typing import TYPE_CHECKING

from . import util

if TYPE_CHECKING:
    from .app import ServerApplication

log = logging.getLogger(__name__)

# Maximum number of pending connections in the socket listen queue
BACKLOG = 2048


class BaseSocket:
    FAMILY: socket.AddressFamily

    def __init__(
        self,
        address: tuple[str, int] | str,
        *,
        is_ssl: bool = False,
        fd: int | None = None,
    ) -> None:
        self.is_ssl = is_ssl
        self.cfg_addr = address
        if fd is None:
            sock = socket.socket(self.FAMILY, socket.SOCK_STREAM)
            bound = False
        else:
            sock = socket.fromfd(fd, self.FAMILY, socket.SOCK_STREAM)
            os.close(fd)
            bound = True

        self.sock: socket.socket | None = self.set_options(sock, bound=bound)

    def __str__(self) -> str:
        assert self.sock is not None, "Socket is closed"
        return f"<socket {self.sock.fileno()}>"

    def __getattr__(self, name: str) -> object:
        return getattr(self.sock, name)

    def accept(self) -> tuple[socket.socket, tuple[str, int] | str]:
        """Accept a connection. Returns (socket object, address)."""
        assert self.sock is not None, "Socket is closed"
        return self.sock.accept()

    def fileno(self) -> int:
        """Return the socket's file descriptor."""
        assert self.sock is not None, "Socket is closed"
        return self.sock.fileno()

    def setblocking(self, flag: bool) -> None:
        """Set blocking or non-blocking mode of the socket."""
        assert self.sock is not None, "Socket is closed"
        return self.sock.setblocking(flag)

    def getsockname(self) -> tuple[str, int] | str:
        assert self.sock is not None, "Socket is closed"
        return self.sock.getsockname()

    def set_options(self, sock: socket.socket, bound: bool = False) -> socket.socket:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if not bound:
            self.bind(sock)
        sock.setblocking(False)
        sock.listen(BACKLOG)
        return sock

    def bind(self, sock: socket.socket) -> None:
        sock.bind(self.cfg_addr)

    def close(self) -> None:
        if self.sock is None:
            return None

        try:
            self.sock.close()
        except OSError as e:
            log.info("Error while closing socket %s", str(e))

        self.sock = None
        return None


class TCPSocket(BaseSocket):
    FAMILY = socket.AF_INET

    def __str__(self) -> str:
        scheme = "https" if self.is_ssl else "http"

        assert self.sock is not None, "Socket is closed"
        addr = self.sock.getsockname()
        return f"{scheme}://{addr[0]}:{addr[1]}"

    def set_options(self, sock: socket.socket, bound: bool = False) -> socket.socket:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return super().set_options(sock, bound=bound)


class TCP6Socket(TCPSocket):
    FAMILY = socket.AF_INET6

    def __str__(self) -> str:
        assert self.sock is not None, "Socket is closed"
        (host, port, _, _) = self.sock.getsockname()
        return f"http://[{host}]:{port}"


class UnixSocket(BaseSocket):
    FAMILY = socket.AF_UNIX

    def __init__(
        self,
        addr: str,
        *,
        is_ssl: bool = False,
        fd: int | None = None,
    ):
        if fd is None:
            try:
                st = os.stat(addr)
            except OSError as e:
                if e.args[0] != errno.ENOENT:
                    raise
            else:
                if stat.S_ISSOCK(st.st_mode):
                    os.remove(addr)
                else:
                    raise ValueError(f"{addr!r} is not a socket")
        super().__init__(addr, is_ssl=is_ssl, fd=fd)

    def __str__(self) -> str:
        return f"unix:{self.cfg_addr}"

    def bind(self, sock: socket.socket) -> None:
        sock.bind(self.cfg_addr)


def _sock_type(addr: tuple[str, int] | str | bytes) -> type[BaseSocket]:
    if isinstance(addr, tuple):
        if util.is_ipv6(addr[0]):
            sock_type = TCP6Socket
        else:
            sock_type = TCPSocket
    elif isinstance(addr, str | bytes):
        sock_type = UnixSocket
    else:
        raise TypeError(f"Unable to create socket from: {addr!r}")
    return sock_type


def create_sockets(app: ServerApplication) -> list[BaseSocket]:
    """
    Create a new socket for the configured addresses.

    If a configured address is a tuple then a TCP socket is created.
    If it is a string, a Unix socket is created. Otherwise, a TypeError is
    raised.
    """
    listeners = []

    # check ssl config early to raise the error on startup
    # only the certfile is needed since it can contains the keyfile
    if app.certfile and not os.path.exists(app.certfile):
        raise ValueError(f'certfile "{app.certfile}" does not exist')

    if app.keyfile and not os.path.exists(app.keyfile):
        raise ValueError(f'keyfile "{app.keyfile}" does not exist')

    for addr in app.address:
        sock_type = _sock_type(addr)
        sock = None
        for i in range(5):
            try:
                sock = sock_type(addr, is_ssl=app.is_ssl)
            except OSError as e:
                if e.args[0] == errno.EADDRINUSE:
                    log.error("Connection in use: %s", str(addr))
                if e.args[0] == errno.EADDRNOTAVAIL:
                    log.error("Invalid address: %s", str(addr))
                msg = "connection to {addr} failed: {error}"
                log.error(msg.format(addr=str(addr), error=str(e)))
                if i < 5:
                    log.debug("Retrying in 1 second.")
                    time.sleep(1)
            else:
                break

        if sock is None:
            log.error("Can't connect to %s", str(addr))
            sys.exit(1)

        listeners.append(sock)

    return listeners


def close_sockets(listeners: list[BaseSocket], unlink: bool = True) -> None:
    for sock in listeners:
        sock_name = sock.getsockname()
        sock.close()
        if unlink and _sock_type(sock_name) is UnixSocket:
            assert isinstance(sock_name, str)
            os.unlink(sock_name)


def ssl_context(certfile: str, keyfile: str | None) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return context


def ssl_wrap_socket(
    sock: socket.socket, certfile: str, keyfile: str | None
) -> ssl.SSLSocket:
    return ssl_context(certfile, keyfile).wrap_socket(sock, server_side=True)
