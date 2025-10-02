"""
Email message and email sending related helper functions.
"""

from __future__ import annotations

import socket

from plain.utils.encoding import punycode


# Cache the hostname, but do it lazily: socket.getfqdn() can take a couple of
# seconds, which slows down the restart of the server.
class CachedDnsName:
    def __str__(self) -> str:
        return self.get_fqdn()

    def get_fqdn(self) -> str:
        if not hasattr(self, "_fqdn"):
            self._fqdn = punycode(socket.getfqdn())
        return self._fqdn


DNS_NAME = CachedDnsName()
