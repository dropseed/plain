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
import select
import socket
import ssl
import sys
from datetime import datetime
from typing import Any

from plain.signals import request_finished, request_started

from .. import http, sock, util
from ..http import wsgi
from . import base

log = logging.getLogger("plain.channels")


class StopWaiting(Exception):
    """exception raised to stop waiting for a connection"""


class SyncWorker(base.Worker):
    def accept(self, listener: sock.BaseSocket) -> None:
        client, addr = listener.accept()
        client.setblocking(True)
        util.close_on_exec(client.fileno())
        self.handle(listener, client, addr)

    def wait(self, timeout: float) -> list[Any] | None:
        try:
            self.notify()
            ret = select.select(self.wait_fds, [], [], timeout)
            if ret[0]:
                if self.PIPE[0] in ret[0]:
                    os.read(self.PIPE[0], 1)
                return ret[0]
            return None

        except OSError as e:
            if e.args[0] == errno.EINTR:
                return self.sockets
            if e.args[0] == errno.EBADF:
                if self.nr < 0:
                    return self.sockets
                else:
                    raise StopWaiting
            raise

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def run_for_one(self, timeout: float) -> None:
        listener = self.sockets[0]
        while self.alive:
            self.notify()

            # Accept a connection. If we get an error telling us
            # that no connection is waiting we fall down to the
            # select which is where we'll wait for a bit for new
            # workers to come give us some love.
            try:
                self.accept(listener)
                # Keep processing clients until no one is waiting. This
                # prevents the need to select() for every client that we
                # process.
                continue

            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.ECONNABORTED, errno.EWOULDBLOCK):
                    raise

            if not self.is_parent_alive():
                return None

            try:
                self.wait(timeout)
            except StopWaiting:
                return None

    def run_for_multiple(self, timeout: float) -> None:
        while self.alive:
            self.notify()

            try:
                ready = self.wait(timeout)
            except StopWaiting:
                return None

            if ready is not None:
                for listener in ready:
                    if listener == self.PIPE[0]:
                        continue

                    try:
                        self.accept(listener)
                    except OSError as e:
                        if e.errno not in (
                            errno.EAGAIN,
                            errno.ECONNABORTED,
                            errno.EWOULDBLOCK,
                        ):
                            raise

            if not self.is_parent_alive():
                return None

    def run(self) -> None:
        # if no timeout is given the worker will never wait and will
        # use the CPU for nothing. This minimal timeout prevent it.
        timeout = self.timeout or 0.5

        # self.socket appears to lose its blocking status after
        # we fork in the arbiter. Reset it here.
        for s in self.sockets:
            s.setblocking(False)

        if len(self.sockets) > 1:
            self.run_for_multiple(timeout)
        else:
            self.run_for_one(timeout)

    def handle(
        self, listener: sock.BaseSocket, client: socket.socket, addr: Any
    ) -> None:
        req = None
        handed_off = False
        try:
            if self.cfg.is_ssl:
                client = sock.ssl_wrap_socket(client, self.cfg)
            parser = http.RequestParser(self.cfg, client, addr)
            req = next(parser)
            handed_off = self.handle_request(listener, req, client, addr)
        except http.errors.NoMoreData as e:
            self.log.debug("Ignored premature client disconnection. %s", e)
        except StopIteration as e:
            self.log.debug("Closing connection. %s", e)
        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("ssl connection closed")
                client.close()
            else:
                self.log.debug("Error processing SSL request.")
                self.handle_error(req, client, addr, e)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error processing request.")
            else:
                if e.errno == errno.ECONNRESET:
                    self.log.debug("Ignoring connection reset")
                elif e.errno == errno.ENOTCONN:
                    self.log.debug("Ignoring socket not connected")
                else:
                    self.log.debug("Ignoring EPIPE")
        except BaseException as e:
            self.handle_error(req, client, addr, e)
        finally:
            # Don't close the socket if it was handed off to the async loop
            if not handed_off:
                util.close(client)

    def handle_request(
        self, listener: sock.BaseSocket, req: Any, client: socket.socket, addr: Any
    ) -> bool:
        """Handle a request. Returns True if the socket was handed off to the async loop."""
        # Check if this is a channel (SSE) request
        channel = self._match_channel(req)
        if channel is not None:
            return self._handle_channel_request(req, client, addr, listener, channel)

        return self._handle_http_request(req, client, addr, listener)

    def _match_channel(self, req: Any) -> Any:
        """Check if the request path matches a registered channel."""
        try:
            from plain.channels import channel_registry

            return channel_registry.match(req.path)
        except Exception:
            return None

    def _handle_channel_request(
        self,
        req: Any,
        client: socket.socket,
        addr: Any,
        listener: sock.BaseSocket,
        channel: Any,
    ) -> bool:
        """Handle an SSE channel request. Returns True if handoff succeeded."""
        try:
            # Create a Plain Request for auth/subscribe (sync context)
            plain_request = wsgi.create_plain_request(
                req, addr, listener.getsockname(), self.cfg
            )

            # Authorize in the sync context — full ORM/session access
            if not channel.authorize(plain_request):
                # Send 403 and let the caller close the socket
                util.write_error(client, 403, "Forbidden", "")
                return False

            # Get subscriptions in the sync context
            subscriptions = channel.subscribe(plain_request)

            # Dup the socket fd — the async side takes ownership of the dup
            dup_fd = os.dup(client.fileno())

            # Hand off to the async event loop
            if (
                hasattr(self, "connection_manager")
                and self.connection_manager is not None
            ):
                self._async_loop.call_soon_threadsafe(
                    self.connection_manager.accept_connection,
                    dup_fd,
                    channel,
                    subscriptions,
                )
                log.debug("Handed off SSE connection for %s", channel.path)
                return True
            else:
                os.close(dup_fd)
                util.write_error(client, 503, "Service Unavailable", "")
                return False

        except Exception:
            self.log.exception("Error handling channel request")
            try:
                util.write_error(client, 500, "Internal Server Error", "")
            except Exception:
                pass
            return False

    def _handle_http_request(
        self,
        req: Any,
        client: socket.socket,
        addr: Any,
        listener: sock.BaseSocket,
    ) -> bool:
        """Handle a regular HTTP request. Always returns False (no handoff)."""
        resp = None
        request_start = datetime.now()
        try:
            resp = wsgi.Response(req, client, self.cfg)
            # Force the connection closed until someone shows
            # a buffering proxy that supports Keep-Alive to
            # the backend.
            resp.force_close()
            self.nr += 1
            if self.nr >= self.max_requests:
                self.log.info("Autorestarting worker after current request.")
                self.alive = False

            # Handle 100-continue
            for hdr_name, hdr_value in req.headers:
                if hdr_name == "EXPECT" and hdr_value.lower() == "100-continue":
                    client.send(b"HTTP/1.1 100 Continue\r\n\r\n")

            # Create Plain Request directly from parsed HTTP data
            plain_request = wsgi.create_plain_request(
                req, addr, listener.getsockname(), self.cfg
            )

            request_started.send(sender=self.__class__)

            # Get response from Plain handler
            response = self.handler.get_response(plain_request)

            # Write response using the server's Response writer
            status = f"{response.status_code} {response.reason_phrase}"
            response_headers = [
                *((k, v) for k, v in response.headers.items() if v is not None),
                *(
                    ("Set-Cookie", c.output(header=""))
                    for c in response.cookies.values()
                ),
            ]
            resp.start_response(status, response_headers)

            for item in response:
                resp.write(item)
            resp.close()

            if hasattr(response, "close"):
                response.close()
        except OSError:
            # pass to next try-except level
            util.reraise(*sys.exc_info())
        except Exception:
            if resp and resp.headers_sent:
                # If the requests have already been sent, we should close the
                # connection to indicate the error.
                self.log.exception("Error handling request")
                try:
                    client.shutdown(socket.SHUT_RDWR)
                    client.close()
                except OSError:
                    pass
                raise StopIteration()
            raise
        finally:
            request_finished.send(sender=self.__class__)
            request_time = datetime.now() - request_start
            environ = wsgi.default_environ(req, client, self.cfg)
            if addr:
                if isinstance(addr, tuple):
                    environ["REMOTE_ADDR"] = addr[0]
                    environ["REMOTE_PORT"] = str(addr[1])
                else:
                    environ["REMOTE_ADDR"] = str(addr)
            self.log.access(resp, req, environ, request_time)
        return False
