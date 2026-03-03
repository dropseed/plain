from __future__ import annotations

import codecs
from functools import cached_property
from typing import TYPE_CHECKING
from urllib.parse import quote

from plain import signals
from plain.http import FileResponse, LimitedStream, QueryDict, Request, parse_cookie
from plain.internal.handlers import base
from plain.utils.http import parse_header_parameters
from plain.utils.regex_helper import _lazy_re_compile

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Any

    from plain.http import ResponseBase

_slashes_re = _lazy_re_compile(rb"/+")

_HTTP_PREFIX = "HTTP_"
_UNPREFIXED_HEADERS = {"CONTENT_TYPE", "CONTENT_LENGTH"}


def _extract_headers_from_environ(environ: dict[str, Any]) -> dict[str, str]:
    """Extract HTTP headers from a WSGI environ dict into a plain dict.

    Converts WSGI-style header names (HTTP_ACCEPT, CONTENT_TYPE) to
    standard HTTP header names (Accept, Content-Type).
    """
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if key.startswith(_HTTP_PREFIX):
            name = key[len(_HTTP_PREFIX) :].replace("_", "-").title()
            headers[name] = value
        elif key in _UNPREFIXED_HEADERS:
            name = key.replace("_", "-").title()
            headers[name] = value
    return headers


class WSGIRequest(Request):
    non_picklable_attrs = Request.non_picklable_attrs | frozenset(["environ"])

    method: str  # Always set from environ, overrides Request.method: str | None

    def __init__(self, environ: dict[str, Any]) -> None:
        super().__init__()

        script_name = get_script_name(environ)
        # If PATH_INFO is empty (e.g. accessing the SCRIPT_NAME URL without a
        # trailing slash), operate as if '/' was requested.
        path_info = get_path_info(environ) or "/"
        self.environ = environ
        self.path_info = path_info
        # be careful to only replace the first slash in the path because of
        # http://test/something and http://test//something being different as
        # stated in RFC 3986.
        self.path = "{}/{}".format(
            script_name.rstrip("/"), path_info.replace("/", "", 1)
        )
        self.environ["PATH_INFO"] = path_info
        self.environ["SCRIPT_NAME"] = script_name
        self.method = environ["REQUEST_METHOD"].upper()

        # Populate base Request attributes from environ
        self.server_name = environ.get("SERVER_NAME", "")
        self.server_port = environ.get("SERVER_PORT", "")
        self.remote_addr = environ.get("REMOTE_ADDR", "")
        self._query_string = environ.get("QUERY_STRING", "")
        self._scheme = environ.get("wsgi.url_scheme", "http")

        # Extract headers from environ (HTTP_* keys + CONTENT_TYPE/CONTENT_LENGTH)
        self._headers = _extract_headers_from_environ(environ)

        # Set content_type, content_params, and encoding
        self.content_type, self.content_params = parse_header_parameters(
            environ.get("CONTENT_TYPE", "")
        )
        if "charset" in self.content_params:
            try:
                codecs.lookup(self.content_params["charset"])
            except LookupError:
                pass
            else:
                self.encoding = self.content_params["charset"]

        try:
            content_length = int(environ.get("CONTENT_LENGTH") or 0)
        except (ValueError, TypeError):
            content_length = 0
        self._stream = LimitedStream(self.environ["wsgi.input"], content_length)
        self._read_started = False

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        for attr in frozenset(["wsgi.errors", "wsgi.input"]):
            if attr in state["environ"]:
                del state["environ"][attr]
        return state

    @cached_property
    def query_params(self) -> QueryDict:
        raw_query_string = get_bytes_from_wsgi(self.environ, "QUERY_STRING", "")
        return QueryDict(raw_query_string, encoding=self.encoding)

    @cached_property
    def cookies(self) -> dict[str, str]:
        raw_cookie = get_str_from_wsgi(self.environ, "HTTP_COOKIE", "")
        return parse_cookie(raw_cookie)


class WSGIHandler(base.BaseHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.load_middleware()

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[[str, list[tuple[str, str]]], Any],
    ) -> ResponseBase | Iterable[bytes]:
        signals.request_started.send(sender=self.__class__, environ=environ)
        request = WSGIRequest(environ)
        response = self.get_response(request)

        response._handler_class = self.__class__

        status = "%d %s" % (response.status_code, response.reason_phrase)  # noqa: UP031
        response_headers = [
            # Filter out None values (used to opt-out of default headers)
            *((k, v) for k, v in response.headers.items() if v is not None),
            *(("Set-Cookie", c.output(header="")) for c in response.cookies.values()),
        ]
        start_response(status, response_headers)
        if (
            isinstance(response, FileResponse)
            and response.file_to_stream is not None
            and environ.get("wsgi.file_wrapper")
        ):
            # If `wsgi.file_wrapper` is used the WSGI server does not call
            # .close on the response, but on the file wrapper. Patch it to use
            # response.close instead which takes care of closing all files.
            response.file_to_stream.close = response.close
            response = environ["wsgi.file_wrapper"](
                response.file_to_stream, response.block_size
            )
        return response


def get_path_info(environ: dict[str, Any]) -> str:
    """Return the HTTP request's PATH_INFO as a string."""
    path_info = get_bytes_from_wsgi(environ, "PATH_INFO", "/")

    def repercent_broken_unicode(path: bytes) -> bytes:
        """
        As per RFC 3987 Section 3.2, step three of converting a URI into an IRI,
        repercent-encode any octet produced that is not part of a strictly legal
        UTF-8 octet sequence.
        """
        while True:
            try:
                path.decode()
            except UnicodeDecodeError as e:
                # CVE-2019-14235: A recursion shouldn't be used since the exception
                # handling uses massive amounts of memory
                repercent = quote(path[e.start : e.end], safe=b"/#%[]=:;$&()+,!?*@'~")
                path = path[: e.start] + repercent.encode() + path[e.end :]
            else:
                return path

    return repercent_broken_unicode(path_info).decode()


def get_script_name(environ: dict[str, Any]) -> str:
    """
    Return the equivalent of the HTTP request's SCRIPT_NAME environment
    variable. If Apache mod_rewrite is used, return what would have been
    the script name prior to any rewriting (so it's the script name as seen
    from the client's perspective).
    """
    # If Apache's mod_rewrite had a whack at the URL, Apache set either
    # SCRIPT_URL or REDIRECT_URL to the full resource URL before applying any
    # rewrites. Unfortunately not every web server (lighttpd!) passes this
    # information through all the time, so FORCE_SCRIPT_NAME, above, is still
    # needed.
    script_url = get_bytes_from_wsgi(environ, "SCRIPT_URL", "") or get_bytes_from_wsgi(
        environ, "REDIRECT_URL", ""
    )

    if script_url:
        if b"//" in script_url:
            # mod_wsgi squashes multiple successive slashes in PATH_INFO,
            # do the same with script_url before manipulating paths (#17133).
            script_url = _slashes_re.sub(b"/", script_url)
        path_info = get_bytes_from_wsgi(environ, "PATH_INFO", "")
        script_name = script_url.removesuffix(path_info)
    else:
        script_name = get_bytes_from_wsgi(environ, "SCRIPT_NAME", "")

    return script_name.decode()


def get_bytes_from_wsgi(environ: dict[str, Any], key: str, default: str) -> bytes:
    """
    Get a value from the WSGI environ dictionary as bytes.

    key and default should be strings.
    """
    value = environ.get(key, default)
    # Non-ASCII values in the WSGI environ are arbitrarily decoded with
    # ISO-8859-1. This is wrong for Plain websites where UTF-8 is the default.
    # Re-encode to recover the original bytestring.
    return value.encode("iso-8859-1")


def get_str_from_wsgi(environ: dict[str, Any], key: str, default: str) -> str:
    """
    Get a value from the WSGI environ dictionary as str.

    key and default should be str objects.
    """
    value = get_bytes_from_wsgi(environ, key, default)
    return value.decode(errors="replace")
