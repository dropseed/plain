from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import io
import re
from typing import TYPE_CHECKING, Any

from ..util import bytes_to_str, split_request_uri
from .body import Body, ChunkedReader, EOFReader, LengthReader
from .errors import (
    InvalidHeader,
    InvalidHeaderName,
    InvalidHTTPVersion,
    InvalidRequestLine,
    InvalidRequestMethod,
    InvalidSchemeHeaders,
    LimitRequestHeaders,
    LimitRequestLine,
    NoMoreData,
    ObsoleteFolding,
    UnsupportedTransferCoding,
)

if TYPE_CHECKING:
    from ..config import Config

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
DEFAULT_MAX_HEADERFIELD_SIZE = 8190

# Request size limits for DDoS protection
LIMIT_REQUEST_LINE = 4094  # Maximum HTTP request line size in bytes
LIMIT_REQUEST_FIELDS = 100  # Maximum number of HTTP header fields
LIMIT_REQUEST_FIELD_SIZE = 8190  # Maximum size of an HTTP header field in bytes

# verbosely on purpose, avoid backslash ambiguity
RFC9110_5_6_2_TOKEN_SPECIALS = r"!#$%&'*+-.^_`|~"
TOKEN_RE = re.compile(rf"[{re.escape(RFC9110_5_6_2_TOKEN_SPECIALS)}0-9a-zA-Z]+")
METHOD_BADCHAR_RE = re.compile("[a-z#]")
# usually 1.0 or 1.1 - RFC9112 permits restricting to single-digit versions
VERSION_RE = re.compile(r"HTTP/(\d)\.(\d)")
RFC9110_5_5_INVALID_AND_DANGEROUS = re.compile(r"[\0\r\n]")


class Message:
    def __init__(self, cfg: Config, unreader: Any, peer_addr: tuple[str, int] | Any):
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.version: tuple[int, int] = (1, 1)
        self.headers: list[tuple[str, str]] = []
        self.trailers: list[tuple[str, str]] = []
        self.body: Body | None = None
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False

        # set headers limits
        self.limit_request_fields = LIMIT_REQUEST_FIELDS
        if self.limit_request_fields <= 0 or self.limit_request_fields > MAX_HEADERS:
            self.limit_request_fields = MAX_HEADERS
        self.limit_request_field_size = LIMIT_REQUEST_FIELD_SIZE
        if self.limit_request_field_size < 0:
            self.limit_request_field_size = DEFAULT_MAX_HEADERFIELD_SIZE

        # set max header buffer size
        max_header_field_size = (
            self.limit_request_field_size or DEFAULT_MAX_HEADERFIELD_SIZE
        )
        self.max_buffer_headers = (
            self.limit_request_fields * (max_header_field_size + 2) + 4
        )

        unused = self.parse(self.unreader)
        self.unreader.unread(unused)
        self.set_body_reader()

    def force_close(self) -> None:
        self.must_close = True

    def parse(self, unreader: Any) -> bytes:
        raise NotImplementedError()

    def parse_headers(
        self, data: bytes, from_trailer: bool = False
    ) -> list[tuple[str, str]]:
        cfg = self.cfg
        headers = []

        # Split lines on \r\n
        lines = [bytes_to_str(line) for line in data.split(b"\r\n")]

        # handle scheme headers
        scheme_header = False
        secure_scheme_headers = {}
        forwarder_headers = []
        if from_trailer:
            # nonsense. either a request is https from the beginning
            #  .. or we are just behind a proxy who does not remove conflicting trailers
            pass
        elif (
            "*" in cfg.forwarded_allow_ips
            or not isinstance(self.peer_addr, tuple)
            or self.peer_addr[0] in cfg.forwarded_allow_ips
        ):
            secure_scheme_headers = cfg.secure_scheme_headers
            forwarder_headers = cfg.forwarder_headers

        # Parse headers into key/value pairs paying attention
        # to continuation lines.
        while lines:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Parse initial header name: value pair.
            curr = lines.pop(0)
            header_length = len(curr) + len("\r\n")
            if curr.find(":") <= 0:
                raise InvalidHeader(curr)
            name, value = curr.split(":", 1)
            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName(name)

            # this is still a dangerous place to do this
            #  but it is more correct than doing it before the pattern match:
            # after we entered Unicode wonderland, 8bits could case-shift into ASCII:
            # b"\xDF".decode("latin-1").upper().encode("ascii") == b"SS"
            name = name.upper()

            value = [value.strip(" \t")]

            # Consume value continuation lines..
            while lines and lines[0].startswith((" ", "\t")):
                # Obsolete folding is not permitted (RFC 7230)
                raise ObsoleteFolding(name)
            value = " ".join(value)

            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name)

            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")

            if name in secure_scheme_headers:
                secure = value == secure_scheme_headers[name]
                scheme = "https" if secure else "http"
                if scheme_header:
                    if scheme != self.scheme:
                        raise InvalidSchemeHeaders()
                else:
                    scheme_header = True
                    self.scheme = scheme

            # ambiguous mapping allows fooling downstream, e.g. merging non-identical headers:
            # X-Forwarded-For: 2001:db8::ha:cc:ed
            # X_Forwarded_For: 127.0.0.1,::1
            # HTTP_X_FORWARDED_FOR = 2001:db8::ha:cc:ed,127.0.0.1,::1
            # Only modify after fixing *ALL* header transformations; network to wsgi env
            if "_" in name:
                if name in forwarder_headers or "*" in forwarder_headers:
                    # This forwarder may override our environment
                    pass
                elif self.cfg.header_map == "dangerous":
                    # as if we did not know we cannot safely map this
                    pass
                elif self.cfg.header_map == "drop":
                    # almost as if it never had been there
                    # but still counts against resource limits
                    continue
                else:
                    # fail-safe fallthrough: refuse
                    raise InvalidHeaderName(name)

            headers.append((name, value))

        return headers

    def set_body_reader(self) -> None:
        chunked = False
        content_length_str: str | None = None

        for name, value in self.headers:
            if name == "CONTENT-LENGTH":
                if content_length_str is not None:
                    raise InvalidHeader("CONTENT-LENGTH", req=self)
                content_length_str = value
            elif name == "TRANSFER-ENCODING":
                # T-E can be a list
                # https://datatracker.ietf.org/doc/html/rfc9112#name-transfer-encoding
                vals = [v.strip() for v in value.split(",")]
                for val in vals:
                    if val.lower() == "chunked":
                        # DANGER: transfer codings stack, and stacked chunking is never intended
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        chunked = True
                    elif val.lower() == "identity":
                        # does not do much, could still plausibly desync from what the proxy does
                        # safe option: nuke it, its never needed
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                    elif val.lower() in ("compress", "deflate", "gzip"):
                        # chunked should be the last one
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        self.force_close()
                    else:
                        raise UnsupportedTransferCoding(value)

        if chunked:
            # two potentially dangerous cases:
            #  a) CL + TE (TE overrides CL.. only safe if the recipient sees it that way too)
            #  b) chunked HTTP/1.0 (always faulty)
            assert self.version is not None, "version should be set during parsing"
            if self.version < (1, 1):
                # framing wonky, see RFC 9112 Section 6.1
                raise InvalidHeader("TRANSFER-ENCODING", req=self)
            if content_length_str is not None:
                # we cannot be certain the message framing we understood matches proxy intent
                #  -> whatever happens next, remaining input must not be trusted
                raise InvalidHeader("CONTENT-LENGTH", req=self)
            self.body = Body(ChunkedReader(self, self.unreader))
        elif content_length_str is not None:
            content_length: int
            try:
                if str(content_length_str).isnumeric():
                    content_length = int(content_length_str)
                else:
                    raise InvalidHeader("CONTENT-LENGTH", req=self)
            except ValueError:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            if content_length < 0:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            self.body = Body(LengthReader(self.unreader, content_length))
        else:
            self.body = Body(EOFReader(self.unreader))

    def should_close(self) -> bool:
        if self.must_close:
            return True
        for h, v in self.headers:
            if h == "CONNECTION":
                v = v.lower().strip(" \t")
                if v == "close":
                    return True
                elif v == "keep-alive":
                    return False
                break
        return self.version <= (1, 0)


class Request(Message):
    def __init__(
        self,
        cfg: Config,
        unreader: Any,
        peer_addr: tuple[str, int] | Any,
        req_number: int = 1,
    ):
        self.method: str | None = None
        self.uri: str | None = None
        self.path: str | None = None
        self.query: str | None = None
        self.fragment: str | None = None

        # get max request line size
        self.limit_request_line = LIMIT_REQUEST_LINE
        if self.limit_request_line < 0 or self.limit_request_line >= MAX_REQUEST_LINE:
            self.limit_request_line = MAX_REQUEST_LINE

        self.req_number = req_number
        super().__init__(cfg, unreader, peer_addr)

    def get_data(self, unreader: Any, buf: io.BytesIO, stop: bool = False) -> None:
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(buf.getvalue())
        buf.write(data)

    def parse(self, unreader: Any) -> bytes:
        buf = io.BytesIO()
        self.get_data(unreader, buf, stop=True)

        # get request line
        line, rbuf = self.read_line(unreader, buf, self.limit_request_line)

        self.parse_request_line(line)
        buf = io.BytesIO()
        buf.write(rbuf)

        # Headers
        data = buf.getvalue()
        idx = data.find(b"\r\n\r\n")

        done = data[:2] == b"\r\n"
        while True:
            idx = data.find(b"\r\n\r\n")
            done = data[:2] == b"\r\n"

            if idx < 0 and not done:
                self.get_data(unreader, buf)
                data = buf.getvalue()
                if len(data) > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
            else:
                break

        if done:
            self.unreader.unread(data[2:])
            return b""

        self.headers = self.parse_headers(data[:idx], from_trailer=False)

        ret = data[idx + 4 :]
        buf = None
        return ret

    def read_line(
        self, unreader: Any, buf: io.BytesIO, limit: int = 0
    ) -> tuple[bytes, bytes]:
        data = buf.getvalue()

        while True:
            idx = data.find(b"\r\n")
            if idx >= 0:
                # check if the request line is too large
                if idx > limit > 0:
                    raise LimitRequestLine(idx, limit)
                break
            if len(data) - 2 > limit > 0:
                raise LimitRequestLine(len(data), limit)
            self.get_data(unreader, buf)
            data = buf.getvalue()

        return (
            data[:idx],  # request line,
            data[idx + 2 :],
        )  # residue in the buffer, skip \r\n

    def parse_request_line(self, line_bytes: bytes) -> None:
        bits = [bytes_to_str(bit) for bit in line_bytes.split(b" ", 2)]
        if len(bits) != 3:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        # Method: RFC9110 Section 9
        self.method = bits[0]

        # Enforce IANA-style method restrictions
        if METHOD_BADCHAR_RE.search(self.method):
            raise InvalidRequestMethod(self.method)
        if not 3 <= len(bits[0]) <= 20:
            raise InvalidRequestMethod(self.method)
        # Standard restriction: RFC9110 token
        if not TOKEN_RE.fullmatch(self.method):
            raise InvalidRequestMethod(self.method)

        # URI
        self.uri = bits[1]

        # Python stdlib explicitly tells us it will not perform validation.
        # https://docs.python.org/3/library/urllib.parse.html#url-parsing-security
        # There are *four* `request-target` forms in rfc9112, none of them can be empty:
        # 1. origin-form, which starts with a slash
        # 2. absolute-form, which starts with a non-empty scheme
        # 3. authority-form, (for CONNECT) which contains a colon after the host
        # 4. asterisk-form, which is an asterisk (`\x2A`)
        # => manually reject one always invalid URI: empty
        if len(self.uri) == 0:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        try:
            parts = split_request_uri(self.uri)
        except ValueError:
            raise InvalidRequestLine(bytes_to_str(line_bytes))
        self.path = parts.path or ""
        self.query = parts.query or ""
        self.fragment = parts.fragment or ""

        # Version
        match = VERSION_RE.fullmatch(bits[2])
        if match is None:
            raise InvalidHTTPVersion(bits[2])
        self.version = (int(match.group(1)), int(match.group(2)))
        if not (1, 0) <= self.version < (2, 0):
            # Only HTTP/1.0 and HTTP/1.1 are supported
            raise InvalidHTTPVersion(self.version)

    def set_body_reader(self) -> None:
        super().set_body_reader()
        if isinstance(self.body.reader, EOFReader):  # type: ignore[union-attr]
            self.body = Body(LengthReader(self.unreader, 0))
