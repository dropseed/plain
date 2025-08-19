import json
import sys
from functools import partial
from http import HTTPStatus
from http.cookies import SimpleCookie
from io import BytesIO, IOBase
from urllib.parse import unquote_to_bytes, urljoin, urlparse, urlsplit

from plain.http import HttpHeaders, QueryDict
from plain.internal import internalcode
from plain.internal.handlers.base import BaseHandler
from plain.internal.handlers.wsgi import WSGIRequest
from plain.json import PlainJSONEncoder
from plain.runtime import settings
from plain.signals import got_request_exception, request_started
from plain.urls import get_resolver
from plain.utils.encoding import force_bytes
from plain.utils.functional import SimpleLazyObject
from plain.utils.http import urlencode
from plain.utils.regex_helper import _lazy_re_compile

from .encoding import encode_multipart
from .exceptions import RedirectCycleError

__all__ = (
    "Client",
    "RequestFactory",
)


_BOUNDARY = "BoUnDaRyStRiNg"
_MULTIPART_CONTENT = f"multipart/form-data; boundary={_BOUNDARY}"
_CONTENT_TYPE_RE = _lazy_re_compile(r".*; charset=([\w-]+);?")
# Structured suffix spec: https://tools.ietf.org/html/rfc6838#section-4.2.8
_JSON_CONTENT_TYPE_RE = _lazy_re_compile(r"^application\/(.+\+)?json")


@internalcode
class FakePayload(IOBase):
    """
    A wrapper around BytesIO that restricts what can be read since data from
    the network can't be sought and cannot be read outside of its content
    length. This makes sure that views can't do anything under the test client
    that wouldn't work in real life.
    """

    def __init__(self, initial_bytes=None):
        self.__content = BytesIO()
        self.__len = 0
        self.read_started = False
        if initial_bytes is not None:
            self.write(initial_bytes)

    def __len__(self):
        return self.__len

    def read(self, size=-1, /):
        if not self.read_started:
            self.__content.seek(0)
            self.read_started = True
        if size == -1 or size is None:
            size = self.__len
        assert self.__len >= size, (
            "Cannot read more than the available bytes from the HTTP incoming data."
        )
        content = self.__content.read(size)
        self.__len -= len(content)
        return content

    def readline(self, size=-1, /):
        if not self.read_started:
            self.__content.seek(0)
            self.read_started = True
        if size == -1 or size is None:
            size = self.__len
        assert self.__len >= size, (
            "Cannot read more than the available bytes from the HTTP incoming data."
        )
        content = self.__content.readline(size)
        self.__len -= len(content)
        return content

    def write(self, b, /):
        if self.read_started:
            raise ValueError("Unable to write a payload after it's been read")
        content = force_bytes(b)
        self.__content.write(content)
        self.__len += len(content)


def _conditional_content_removal(request, response):
    """
    Simulate the behavior of most web servers by removing the content of
    responses for HEAD requests, 1xx, 204, and 304 responses. Ensure
    compliance with RFC 9112 Section 6.3.
    """
    if 100 <= response.status_code < 200 or response.status_code in (204, 304):
        if response.streaming:
            response.streaming_content = []
        else:
            response.content = b""
    if request.method == "HEAD":
        if response.streaming:
            response.streaming_content = []
        else:
            response.content = b""
    return response


class ClientHandler(BaseHandler):
    """
    An HTTP Handler that can be used for testing purposes. Use the WSGI
    interface to compose requests, but return the raw Response object with
    the originating WSGIRequest attached to its ``wsgi_request`` attribute.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __call__(self, environ):
        # Set up middleware if needed. We couldn't do this earlier, because
        # settings weren't available.
        if self._middleware_chain is None:
            self.load_middleware()

        request_started.send(sender=self.__class__, environ=environ)
        request = WSGIRequest(environ)

        # Request goes through middleware.
        response = self.get_response(request)

        # Simulate behaviors of most web servers.
        _conditional_content_removal(request, response)

        # Attach the originating request to the response so that it could be
        # later retrieved.
        response.wsgi_request = request

        # Emulate a WSGI server by calling the close method on completion.
        response.close()

        return response


class RequestFactory:
    """
    Class that lets you create mock Request objects for use in testing.

    Usage:

    rf = RequestFactory()
    get_request = rf.get('/hello/')
    post_request = rf.post('/submit/', {'foo': 'bar'})

    Once you have a request object you can pass it to any view function,
    just as if that view had been hooked up using a urlrouter.
    """

    def __init__(self, *, json_encoder=PlainJSONEncoder, headers=None, **defaults):
        self.json_encoder = json_encoder
        self.defaults = defaults
        self.cookies = SimpleCookie()
        self.errors = BytesIO()
        if headers:
            self.defaults.update(HttpHeaders.to_wsgi_names(headers))

    def _base_environ(self, **request):
        """
        The base environment for a request.
        """
        # This is a minimal valid WSGI environ dictionary, plus:
        # - HTTP_COOKIE: for cookie support,
        # - REMOTE_ADDR: often useful, see #8551.
        # See https://www.python.org/dev/peps/pep-3333/#environ-variables
        return {
            "HTTP_COOKIE": "; ".join(
                sorted(
                    f"{morsel.key}={morsel.coded_value}"
                    for morsel in self.cookies.values()
                )
            ),
            "PATH_INFO": "/",
            "REMOTE_ADDR": "127.0.0.1",
            "REQUEST_METHOD": "GET",
            "SCRIPT_NAME": "",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": FakePayload(b""),
            "wsgi.errors": self.errors,
            "wsgi.multiprocess": True,
            "wsgi.multithread": False,
            "wsgi.run_once": False,
            **self.defaults,
            **request,
        }

    def request(self, **request):
        "Construct a generic request object."
        return WSGIRequest(self._base_environ(**request))

    def _encode_data(self, data, content_type):
        if content_type is _MULTIPART_CONTENT:
            return encode_multipart(_BOUNDARY, data)
        else:
            # Encode the content so that the byte representation is correct.
            match = _CONTENT_TYPE_RE.match(content_type)
            if match:
                charset = match[1]
            else:
                charset = settings.DEFAULT_CHARSET
            return force_bytes(data, encoding=charset)

    def _encode_json(self, data, content_type):
        """
        Return encoded JSON if data is a dict, list, or tuple and content_type
        is application/json.
        """
        should_encode = _JSON_CONTENT_TYPE_RE.match(content_type) and isinstance(
            data, dict | list | tuple
        )
        return json.dumps(data, cls=self.json_encoder) if should_encode else data

    def _get_path(self, parsed):
        path = parsed.path
        # If there are parameters, add them
        if parsed.params:
            path += ";" + parsed.params
        path = unquote_to_bytes(path)
        # Replace the behavior where non-ASCII values in the WSGI environ are
        # arbitrarily decoded with ISO-8859-1.
        # Refs comment in `get_bytes_from_wsgi()`.
        return path.decode("iso-8859-1")

    def get(self, path, data=None, secure=True, *, headers=None, **extra):
        """Construct a GET request."""
        data = {} if data is None else data
        return self.generic(
            "GET",
            path,
            secure=secure,
            headers=headers,
            **{
                "QUERY_STRING": urlencode(data, doseq=True),
                **extra,
            },
        )

    def post(
        self,
        path,
        data=None,
        content_type=_MULTIPART_CONTENT,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Construct a POST request."""
        data = self._encode_json({} if data is None else data, content_type)
        post_data = self._encode_data(data, content_type)

        return self.generic(
            "POST",
            path,
            post_data,
            content_type,
            secure=secure,
            headers=headers,
            **extra,
        )

    def head(self, path, data=None, secure=True, *, headers=None, **extra):
        """Construct a HEAD request."""
        data = {} if data is None else data
        return self.generic(
            "HEAD",
            path,
            secure=secure,
            headers=headers,
            **{
                "QUERY_STRING": urlencode(data, doseq=True),
                **extra,
            },
        )

    def trace(self, path, secure=True, *, headers=None, **extra):
        """Construct a TRACE request."""
        return self.generic("TRACE", path, secure=secure, headers=headers, **extra)

    def options(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        "Construct an OPTIONS request."
        return self.generic(
            "OPTIONS", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def put(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Construct a PUT request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PUT", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def patch(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Construct a PATCH request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "PATCH", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def delete(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Construct a DELETE request."""
        data = self._encode_json(data, content_type)
        return self.generic(
            "DELETE", path, data, content_type, secure=secure, headers=headers, **extra
        )

    def generic(
        self,
        method,
        path,
        data="",
        content_type="application/octet-stream",
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Construct an arbitrary HTTP request."""
        parsed = urlparse(str(path))  # path can be lazy
        data = force_bytes(data, settings.DEFAULT_CHARSET)
        r = {
            "PATH_INFO": self._get_path(parsed),
            "REQUEST_METHOD": method,
            "SERVER_PORT": "443" if secure else "80",
            "wsgi.url_scheme": "https" if secure else "http",
        }
        if data:
            r.update(
                {
                    "CONTENT_LENGTH": str(len(data)),
                    "CONTENT_TYPE": content_type,
                    "wsgi.input": FakePayload(data),
                }
            )
        if headers:
            extra.update(HttpHeaders.to_wsgi_names(headers))
        r.update(extra)
        # If QUERY_STRING is absent or empty, we want to extract it from the URL.
        if not r.get("QUERY_STRING"):
            # WSGI requires latin-1 encoded strings. See get_path_info().
            query_string = parsed[4].encode().decode("iso-8859-1")
            r["QUERY_STRING"] = query_string
        return self.request(**r)


class Client(RequestFactory):
    """
    A class that can act as a client for testing purposes.

    It allows the user to compose GET and POST requests, and
    obtain the response that the server gave to those requests.
    The server Response objects are annotated with the details
    of the contexts and templates that were rendered during the
    process of serving the request.

    Client objects are stateful - they will retain cookie (and
    thus session) details for the lifetime of the Client instance.

    This is not intended as a replacement for Twill/Selenium or
    the like - it is here to allow testing against the
    contexts and templates produced by a view, rather than the
    HTML rendered to the end-user.
    """

    def __init__(
        self,
        raise_request_exception=True,
        *,
        headers=None,
        **defaults,
    ):
        super().__init__(headers=headers, **defaults)
        self.handler = ClientHandler()
        self.raise_request_exception = raise_request_exception
        self.exc_info = None
        self.extra = None
        self.headers = None

    def request(self, **request):
        """
        Make a generic request. Compose the environment dictionary and pass
        to the handler, return the result of the handler. Assume defaults for
        the query environment, which can be overridden using the arguments to
        the request.
        """
        environ = self._base_environ(**request)

        # Capture exceptions created by the handler.
        exception_uid = f"request-exception-{id(request)}"
        got_request_exception.connect(self.store_exc_info, dispatch_uid=exception_uid)
        try:
            response = self.handler(environ)
        finally:
            # signals.template_rendered.disconnect(dispatch_uid=signal_uid)
            got_request_exception.disconnect(dispatch_uid=exception_uid)
        # Check for signaled exceptions.
        self.check_exception(response)
        # Save the client and request that stimulated the response.
        response.client = self
        response.request = request
        response.json = partial(self._parse_json, response)

        # If the request had a user attached, make it available on the response.
        if hasattr(response.wsgi_request, "user"):
            response.user = response.wsgi_request.user

        # Attach the ResolverMatch instance to the response.
        resolver = get_resolver()
        response.resolver_match = SimpleLazyObject(
            lambda: resolver.resolve(request["PATH_INFO"]),
        )

        # Update persistent cookie data.
        if response.cookies:
            self.cookies.update(response.cookies)
        return response

    def get(
        self,
        path,
        data=None,
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Request a response from the server using GET."""
        self.extra = extra
        self.headers = headers
        response = super().get(path, data=data, secure=secure, headers=headers, **extra)
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
        return response

    def post(
        self,
        path,
        data=None,
        content_type=_MULTIPART_CONTENT,
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Request a response from the server using POST."""
        self.extra = extra
        self.headers = headers
        response = super().post(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
            )
        return response

    def head(
        self,
        path,
        data=None,
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Request a response from the server using HEAD."""
        self.extra = extra
        self.headers = headers
        response = super().head(
            path, data=data, secure=secure, headers=headers, **extra
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
        return response

    def options(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Request a response from the server using OPTIONS."""
        self.extra = extra
        self.headers = headers
        response = super().options(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
            )
        return response

    def put(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Send a resource to the server using PUT."""
        self.extra = extra
        self.headers = headers
        response = super().put(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
            )
        return response

    def patch(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Send a resource to the server using PATCH."""
        self.extra = extra
        self.headers = headers
        response = super().patch(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
            )
        return response

    def delete(
        self,
        path,
        data="",
        content_type="application/octet-stream",
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Send a DELETE request to the server."""
        self.extra = extra
        self.headers = headers
        response = super().delete(
            path,
            data=data,
            content_type=content_type,
            secure=secure,
            headers=headers,
            **extra,
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, content_type=content_type, headers=headers, **extra
            )
        return response

    def trace(
        self,
        path,
        data="",
        follow=False,
        secure=True,
        *,
        headers=None,
        **extra,
    ):
        """Send a TRACE request to the server."""
        self.extra = extra
        self.headers = headers
        response = super().trace(
            path, data=data, secure=secure, headers=headers, **extra
        )
        if follow:
            response = self._handle_redirects(
                response, data=data, headers=headers, **extra
            )
        return response

    def _handle_redirects(
        self,
        response,
        data="",
        content_type="",
        headers=None,
        **extra,
    ):
        """
        Follow any redirects by requesting responses from the server using GET.
        """
        response.redirect_chain = []
        redirect_status_codes = (
            HTTPStatus.MOVED_PERMANENTLY,
            HTTPStatus.FOUND,
            HTTPStatus.SEE_OTHER,
            HTTPStatus.TEMPORARY_REDIRECT,
            HTTPStatus.PERMANENT_REDIRECT,
        )
        while response.status_code in redirect_status_codes:
            response_url = response.url
            redirect_chain = response.redirect_chain
            redirect_chain.append((response_url, response.status_code))

            url = urlsplit(response_url)
            if url.scheme:
                extra["wsgi.url_scheme"] = url.scheme
            if url.hostname:
                extra["SERVER_NAME"] = url.hostname
            if url.port:
                extra["SERVER_PORT"] = str(url.port)

            path = url.path
            # RFC 3986 Section 6.2.3: Empty path should be normalized to "/".
            if not path and url.netloc:
                path = "/"
            # Prepend the request path to handle relative path redirects
            if not path.startswith("/"):
                path = urljoin(response.request["PATH_INFO"], path)

            if response.status_code in (
                HTTPStatus.TEMPORARY_REDIRECT,
                HTTPStatus.PERMANENT_REDIRECT,
            ):
                # Preserve request method and query string (if needed)
                # post-redirect for 307/308 responses.
                request_method = response.request["REQUEST_METHOD"].lower()
                if request_method not in ("get", "head"):
                    extra["QUERY_STRING"] = url.query
                request_method = getattr(self, request_method)
            else:
                request_method = self.get
                data = QueryDict(url.query)
                content_type = None

            response = request_method(
                path,
                data=data,
                content_type=content_type,
                follow=False,
                headers=headers,
                **extra,
            )
            response.redirect_chain = redirect_chain

            if redirect_chain[-1] in redirect_chain[:-1]:
                # Check that we're not redirecting to somewhere we've already
                # been to, to prevent loops.
                raise RedirectCycleError(
                    "Redirect loop detected.", last_response=response
                )
            if len(redirect_chain) > 20:
                # Such a lengthy chain likely also means a loop, but one with
                # a growing path, changing view, or changing query argument;
                # 20 is the value of "network.http.redirection-limit" from Firefox.
                raise RedirectCycleError("Too many redirects.", last_response=response)

        return response

    def store_exc_info(self, **kwargs):
        """Store exceptions when they are generated by a view."""
        self.exc_info = sys.exc_info()

    def check_exception(self, response):
        """
        Look for a signaled exception, clear the current context exception
        data, re-raise the signaled exception, and clear the signaled exception
        from the local cache.
        """
        response.exc_info = self.exc_info
        if self.exc_info:
            _, exc_value, _ = self.exc_info
            self.exc_info = None
            if self.raise_request_exception:
                raise exc_value

    @property
    def session(self):
        """Return the current session variables."""
        from plain.sessions.test import get_client_session

        return get_client_session(self)

    def force_login(self, user):
        from plain.auth.test import login_client

        login_client(self, user)

    def logout(self):
        """Log out the user by removing the cookies and session object."""
        from plain.auth.test import logout_client

        logout_client(self)

    def _parse_json(self, response, **extra):
        if not hasattr(response, "_json"):
            if not _JSON_CONTENT_TYPE_RE.match(response.headers.get("Content-Type")):
                raise ValueError(
                    'Content-Type header is "{}", not "application/json"'.format(
                        response.headers.get("Content-Type")
                    )
                )
            response._json = json.loads(
                response.content.decode(response.charset), **extra
            )
        return response._json
