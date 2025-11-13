from __future__ import annotations

from collections.abc import Iterator

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
from typing import TYPE_CHECKING, Any

from .message import Request
from .unreader import IterUnreader, SocketUnreader

if TYPE_CHECKING:
    import socket

    from ..config import Config


class Parser:
    mesg_class: type[Request] | None = None

    def __init__(
        self,
        cfg: Config,
        source: socket.socket | Any,
        source_addr: tuple[str, int] | Any,
    ) -> None:
        self.cfg = cfg
        if hasattr(source, "recv"):
            self.unreader = SocketUnreader(source)
        else:
            self.unreader = IterUnreader(source)
        self.mesg = None
        self.source_addr = source_addr

        # request counter (for keepalive connetions)
        self.req_count = 0

    def __iter__(self) -> Iterator[Request]:
        return self

    def __next__(self) -> Request:
        # Stop if HTTP dictates a stop.
        if self.mesg and self.mesg.should_close():
            raise StopIteration()

        # Discard any unread body of the previous message
        if self.mesg and self.mesg.body:
            data = self.mesg.body.read(8192)
            while data:
                data = self.mesg.body.read(8192)

        # Parse the next request
        self.req_count += 1
        assert self.mesg_class is not None, "mesg_class must be set by subclass"
        self.mesg = self.mesg_class(
            self.cfg, self.unreader, self.source_addr, self.req_count
        )
        if not self.mesg:
            raise StopIteration()
        return self.mesg

    next = __next__


class RequestParser(Parser):
    mesg_class = Request
