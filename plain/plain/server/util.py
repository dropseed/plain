from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import ast
import email.utils
import errno
import fcntl
import html
import importlib
import inspect
import io
import logging
import os
import random
import re
import socket
import sys
import textwrap
import time
import traceback
import urllib.parse
import warnings
from collections.abc import Callable
from typing import Any

from .errors import AppImportError
from .workers import SUPPORTED_WORKERS

# Server and Date aren't technically hop-by-hop
# headers, but they are in the purview of the
# origin server which the WSGI spec says we should
# act like. So we drop them and add our own.
#
# In the future, concatenation server header values
# might be better, but nothing else does it and
# dropping them is easier.
hop_headers = set(
    """
    connection keep-alive proxy-authenticate proxy-authorization
    te trailers transfer-encoding upgrade
    server date
    """.split()
)


def load_class(
    uri: str | type,
    default: str = "plain.server.workers.sync.SyncWorker",
    section: str = "plain.server.workers",
) -> type:
    if inspect.isclass(uri):
        return uri  # type: ignore[return-value]

    components = uri.split(".")  # type: ignore[union-attr]
    if len(components) == 1:
        # Handle short names like "sync" or "gthread"
        if uri.startswith("#"):  # type: ignore[union-attr]
            uri = uri[1:]  # type: ignore[union-attr]

        if uri in SUPPORTED_WORKERS:
            components = SUPPORTED_WORKERS[uri].split(".")
        else:
            exc_msg = f"Worker type {uri!r} not found in SUPPORTED_WORKERS"
            raise RuntimeError(exc_msg)

    klass = components.pop(-1)

    try:
        mod = importlib.import_module(".".join(components))
    except Exception:
        exc = traceback.format_exc()
        msg = "class uri %r invalid or not found: \n\n[%s]"
        raise RuntimeError(msg % (uri, exc))
    return getattr(mod, klass)


positionals = (
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


def get_arity(f: Callable[..., Any]) -> int:
    sig = inspect.signature(f)
    arity = 0

    for param in sig.parameters.values():
        if param.kind in positionals:
            arity += 1

    return arity


if sys.platform.startswith("win"):

    def _waitfor(
        func: Callable[[str], None], pathname: str, waitall: bool = False
    ) -> None:
        # Perform the operation
        func(pathname)
        # Now setup the wait loop
        if waitall:
            dirname = pathname
        else:
            dirname, name = os.path.split(pathname)
            dirname = dirname or "."
        # Check for `pathname` to be removed from the filesystem.
        # The exponential backoff of the timeout amounts to a total
        # of ~1 second after which the deletion is probably an error
        # anyway.
        # Testing on a i7@4.3GHz shows that usually only 1 iteration is
        # required when contention occurs.
        timeout = 0.001
        while timeout < 1.0:
            # Note we are only testing for the existence of the file(s) in
            # the contents of the directory regardless of any security or
            # access rights.  If we have made it this far, we have sufficient
            # permissions to do that much using Python's equivalent of the
            # Windows API FindFirstFile.
            # Other Windows APIs can fail or give incorrect results when
            # dealing with files that are pending deletion.
            L = os.listdir(dirname)
            if not L if waitall else name in L:
                return None
            # Increase the timeout and try again
            time.sleep(timeout)
            timeout *= 2
        warnings.warn(
            "tests may fail, delete still pending for " + pathname,
            RuntimeWarning,
            stacklevel=4,
        )
        return None

    def _unlink(filename: str) -> None:
        _waitfor(os.unlink, filename)
        return None
else:
    _unlink = os.unlink


def unlink(filename: str) -> None:
    try:
        _unlink(filename)
    except OSError as error:
        # The filename need not exist.
        if error.errno not in (errno.ENOENT, errno.ENOTDIR):
            raise


def is_ipv6(addr: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6, addr)
    except OSError:  # not a valid address
        return False
    except ValueError:  # ipv6 not supported on this platform
        return False
    return True


def parse_address(netloc: str, default_port: str = "8000") -> str | tuple[str, int]:
    if re.match(r"unix:(//)?", netloc):
        return re.split(r"unix:(//)?", netloc)[-1]

    if netloc.startswith("tcp://"):
        netloc = netloc.split("tcp://")[1]
    host, port = netloc, default_port

    if "[" in netloc and "]" in netloc:
        host = netloc.split("]")[0][1:]
        port = (netloc.split("]:") + [default_port])[1]
    elif ":" in netloc:
        host, port = (netloc.split(":") + [default_port])[:2]
    elif netloc == "":
        host, port = "0.0.0.0", default_port

    try:
        port = int(port)
    except ValueError:
        raise RuntimeError(f"{port!r} is not a valid port number.")

    return host.lower(), port


def close_on_exec(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    flags |= fcntl.FD_CLOEXEC
    fcntl.fcntl(fd, fcntl.F_SETFD, flags)


def set_non_blocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def close(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


def write_chunk(sock: socket.socket, data: str | bytes) -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")
    chunk_size = f"{len(data):X}\r\n"
    chunk = b"".join([chunk_size.encode("utf-8"), data, b"\r\n"])
    sock.sendall(chunk)


def write(sock: socket.socket, data: str | bytes, chunked: bool = False) -> None:
    if chunked:
        return write_chunk(sock, data)
    sock.sendall(data)


def write_nonblock(
    sock: socket.socket, data: str | bytes, chunked: bool = False
) -> None:
    timeout = sock.gettimeout()
    if timeout != 0.0:
        try:
            sock.setblocking(False)
            return write(sock, data, chunked)
        finally:
            sock.setblocking(True)
    else:
        return write(sock, data, chunked)


def write_error(sock: socket.socket, status_int: int, reason: str, mesg: str) -> None:
    html_error = textwrap.dedent("""\
    <html>
      <head>
        <title>%(reason)s</title>
      </head>
      <body>
        <h1><p>%(reason)s</p></h1>
        %(mesg)s
      </body>
    </html>
    """) % {"reason": reason, "mesg": html.escape(mesg)}

    http = textwrap.dedent("""\
    HTTP/1.1 %s %s\r
    Connection: close\r
    Content-Type: text/html\r
    Content-Length: %d\r
    \r
    %s""") % (str(status_int), reason, len(html_error), html_error)
    write_nonblock(sock, http.encode("latin1"))


def _called_with_wrong_args(f: Any) -> bool:
    """Check whether calling a function raised a ``TypeError`` because
    the call failed or because something in the function raised the
    error.

    :param f: The function that was called.
    :return: ``True`` if the call failed.
    """
    tb = sys.exc_info()[2]

    try:
        while tb is not None:
            if tb.tb_frame.f_code is f.__code__:
                # In the function, it was called successfully.
                return False

            tb = tb.tb_next

        # Didn't reach the function.
        return True
    finally:
        # Delete tb to break a circular reference in Python 2.
        # https://docs.python.org/2/library/sys.html#sys.exc_info
        del tb


def import_app(module: str) -> Callable[..., Any]:
    parts = module.split(":", 1)
    if len(parts) == 1:
        obj = "application"
    else:
        module, obj = parts[0], parts[1]

    try:
        mod = importlib.import_module(module)
    except ImportError:
        if module.endswith(".py") and os.path.exists(module):
            msg = "Failed to find application, did you mean '%s:%s'?"
            raise ImportError(msg % (module.rsplit(".", 1)[0], obj))
        raise

    # Parse obj as a single expression to determine if it's a valid
    # attribute name or function call.
    try:
        expression = ast.parse(obj, mode="eval").body
    except SyntaxError:
        raise AppImportError(
            f"Failed to parse {obj!r} as an attribute name or function call."
        )

    if isinstance(expression, ast.Name):
        name = expression.id
        args = kwargs = None
    elif isinstance(expression, ast.Call):
        # Ensure the function name is an attribute name only.
        if not isinstance(expression.func, ast.Name):
            raise AppImportError(f"Function reference must be a simple name: {obj!r}")

        name = expression.func.id

        # Parse the positional and keyword arguments as literals.
        try:
            args = [ast.literal_eval(arg) for arg in expression.args]
            kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in expression.keywords}
        except ValueError:
            # literal_eval gives cryptic error messages, show a generic
            # message with the full expression instead.
            raise AppImportError(
                f"Failed to parse arguments as literal values: {obj!r}"
            )
    else:
        raise AppImportError(
            f"Failed to parse {obj!r} as an attribute name or function call."
        )

    is_debug = logging.root.level == logging.DEBUG
    try:
        app = getattr(mod, name)
    except AttributeError:
        if is_debug:
            traceback.print_exception(*sys.exc_info())
        raise AppImportError(f"Failed to find attribute {name!r} in {module!r}.")

    # If the expression was a function call, call the retrieved object
    # to get the real application.
    if args is not None:
        try:
            app = app(*args, **kwargs)
        except TypeError as e:
            # If the TypeError was due to bad arguments to the factory
            # function, show Python's nice error message without a
            # traceback.
            if _called_with_wrong_args(app):
                raise AppImportError(
                    "".join(traceback.format_exception_only(TypeError, e)).strip()
                )

            # Otherwise it was raised from within the function, show the
            # full traceback.
            raise

    if app is None:
        raise AppImportError(f"Failed to find application object: {obj!r}")

    if not callable(app):
        raise AppImportError("Application object must be callable.")
    return app


def getcwd() -> str:
    # get current path, try to use PWD env first
    try:
        a = os.stat(os.environ["PWD"])
        b = os.stat(os.getcwd())
        if a.st_ino == b.st_ino and a.st_dev == b.st_dev:
            cwd = os.environ["PWD"]
        else:
            cwd = os.getcwd()
    except Exception:
        cwd = os.getcwd()
    return cwd


def http_date(timestamp: float | None = None) -> str:
    """Return the current date and time formatted for a message header."""
    if timestamp is None:
        timestamp = time.time()
    s = email.utils.formatdate(timestamp, localtime=False, usegmt=True)
    return s


def is_hoppish(header: str) -> bool:
    return header.lower().strip() in hop_headers


def seed() -> None:
    try:
        random.seed(os.urandom(64))
    except NotImplementedError:
        random.seed(f"{time.time()}.{os.getpid()}")


def check_is_writable(path: str) -> None:
    try:
        with open(path, "a") as f:
            f.close()
    except OSError as e:
        raise RuntimeError(f"Error: '{path}' isn't writable [{e!r}]")


def to_bytestring(value: str | bytes, encoding: str = "utf8") -> bytes:
    """Converts a string argument to a byte string"""
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not a string")

    return value.encode(encoding)


def has_fileno(obj: Any) -> bool:
    if not hasattr(obj, "fileno"):
        return False

    # check BytesIO case and maybe others
    try:
        obj.fileno()
    except (AttributeError, OSError, io.UnsupportedOperation):
        return False

    return True


def warn(msg: str) -> None:
    print("!!!", file=sys.stderr)

    lines = msg.splitlines()
    for i, line in enumerate(lines):
        if i == 0:
            line = f"WARNING: {line}"
        print(f"!!! {line}", file=sys.stderr)

    print("!!!\n", file=sys.stderr)
    sys.stderr.flush()


def make_fail_app(msg: str | bytes) -> Callable[..., Any]:
    msg = to_bytestring(msg)

    def app(environ: Any, start_response: Any) -> list[bytes]:
        start_response(
            "500 Internal Server Error",
            [("Content-Type", "text/plain"), ("Content-Length", str(len(msg)))],
        )
        return [msg]

    return app


def split_request_uri(uri: str) -> urllib.parse.SplitResult:
    if uri.startswith("//"):
        # When the path starts with //, urlsplit considers it as a
        # relative uri while the RFC says we should consider it as abs_path
        # http://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html#sec5.1.2
        # We use temporary dot prefix to workaround this behaviour
        parts = urllib.parse.urlsplit("." + uri)
        return parts._replace(path=parts.path[1:])

    return urllib.parse.urlsplit(uri)


# From six.reraise
def reraise(
    tp: type[BaseException], value: BaseException | None, tb: Any = None
) -> None:
    try:
        if value is None:
            value = tp()
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value
    finally:
        value = None
        tb = None


def bytes_to_str(b: str | bytes) -> str:
    if isinstance(b, str):
        return b
    return str(b, "latin1")


def unquote_to_wsgi_str(string: str) -> str:
    return urllib.parse.unquote_to_bytes(string).decode("latin-1")
