from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
# Please remember to run "make -C docs html" after update "desc" attributes.
import argparse
import copy
import inspect
import ipaddress
import os
import re
import sys
import textwrap
from typing import Any

import plain.runtime

from . import util
from .errors import ConfigError
from .reloader import reloader_engines

KNOWN_SETTINGS = []
PLATFORM = sys.platform


def make_settings(ignore: tuple[str, ...] | None = None) -> dict[str, Setting]:
    settings = {}
    ignore = ignore or ()
    for s in KNOWN_SETTINGS:
        setting = s()
        if setting.name in ignore:
            continue
        settings[setting.name] = setting.copy()
    return settings


def auto_int(_: Any, x: str) -> int:
    # for compatible with octal numbers in python3
    if re.match(r"0(\d)", x, re.IGNORECASE):
        x = x.replace("0", "0o", 1)
    return int(x, 0)


class Config:
    def __init__(self, usage: str | None = None, prog: str | None = None) -> None:
        self.settings = make_settings()
        self.usage = usage
        self.prog = prog or os.path.basename(sys.argv[0])
        self.env_orig = os.environ.copy()

    def __str__(self) -> str:
        lines = []
        kmax = max(len(k) for k in self.settings)
        for k in sorted(self.settings):
            v = self.settings[k].value
            if callable(v):
                v = f"<{v.__qualname__}()>"
            lines.append("{k:{kmax}} = {v}".format(k=k, v=v, kmax=kmax))
        return "\n".join(lines)

    def __getattr__(self, name: str) -> Any:
        if name not in self.settings:
            raise AttributeError(f"No configuration setting for: {name}")
        return self.settings[name].get()

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "settings" and name in self.settings:
            raise AttributeError("Invalid access!")
        super().__setattr__(name, value)

    def set(self, name: str, value: Any) -> None:
        if name not in self.settings:
            raise AttributeError(f"No configuration setting for: {name}")
        self.settings[name].set(value)

    def parser(self) -> argparse.ArgumentParser:
        kwargs = {"usage": self.usage, "prog": self.prog}
        parser = argparse.ArgumentParser(**kwargs)
        parser.add_argument(
            "-v",
            "--version",
            action="version",
            default=argparse.SUPPRESS,
            version="%(prog)s (version " + plain.runtime.__version__ + ")\n",
            help="show program's version number and exit",
        )
        parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

        keys = sorted(self.settings, key=self.settings.__getitem__)
        for k in keys:
            self.settings[k].add_option(parser)

        return parser

    @property
    def worker_class_str(self) -> str:
        uri = self.settings["worker_class"].get()

        if isinstance(uri, str):
            # are we using a threaded worker?
            is_sync = uri.endswith("SyncWorker") or uri == "sync"
            if is_sync and self.threads > 1:
                return "gthread"
            return uri
        return uri.__name__

    @property
    def worker_class(self) -> type:
        uri = self.settings["worker_class"].get()

        # are we using a threaded worker?
        is_sync = isinstance(uri, str) and (uri.endswith("SyncWorker") or uri == "sync")
        if is_sync and self.threads > 1:
            uri = "plain.server.workers.gthread.ThreadWorker"

        worker_class = util.load_class(uri)
        if hasattr(worker_class, "setup"):
            worker_class.setup()  # type: ignore[call-non-callable]  # hasattr check doesn't narrow type
        return worker_class

    @property
    def address(self) -> list[tuple[str, int] | str]:
        s = self.settings["bind"].get()
        return [util.parse_address(util.bytes_to_str(bind)) for bind in s]

    @property
    def proc_name(self) -> str:
        pn = self.settings["proc_name"].get()
        if pn is not None:
            return pn
        else:
            return self.settings["default_proc_name"].get()

    @property
    def logger_class(self) -> type:
        uri = self.settings["logger_class"].get()
        if uri == "simple":
            # support the default
            uri = LoggerClass.default

        logger_class = util.load_class(
            uri, default="plain.server.glogging.Logger", section="plain.server.loggers"
        )

        if hasattr(logger_class, "install"):
            logger_class.install()  # type: ignore[call-non-callable]  # hasattr check doesn't narrow type
        return logger_class

    @property
    def is_ssl(self) -> bool:
        return self.certfile or self.keyfile

    @property
    def ssl_options(self) -> dict[str, Any]:
        opts = {}
        for name, value in self.settings.items():
            if value.section == "SSL":
                opts[name] = value.get()
        return opts

    @property
    def sendfile(self) -> bool:
        if self.settings["sendfile"].get() is not None:
            return False

        if "SENDFILE" in os.environ:
            sendfile = os.environ["SENDFILE"].lower()
            return sendfile in ["y", "1", "yes", "true"]

        return True

    @property
    def reuse_port(self) -> bool:
        return self.settings["reuse_port"].get()


class SettingMeta(type):
    def __new__(cls, name: str, bases: tuple[type, ...], attrs: dict[str, Any]) -> type:
        super_new = super().__new__
        parents = [b for b in bases if isinstance(b, SettingMeta)]
        if not parents:
            return super_new(cls, name, bases, attrs)

        attrs["order"] = len(KNOWN_SETTINGS)
        attrs["validator"] = staticmethod(attrs["validator"])

        new_class = super_new(cls, name, bases, attrs)
        new_class.fmt_desc(attrs.get("desc", ""))
        KNOWN_SETTINGS.append(new_class)
        return new_class

    def fmt_desc(cls, desc: str) -> None:
        desc = textwrap.dedent(desc).strip()
        setattr(cls, "desc", desc)
        setattr(cls, "short", desc.splitlines()[0])


class Setting:
    name = None
    value = None
    section = None
    cli = None
    validator = None
    type = None
    meta = None
    action = None
    default = None
    short = None
    desc = None
    nargs = None
    const = None

    def __init__(self) -> None:
        if self.default is not None:
            self.set(self.default)

    def add_option(self, parser: argparse.ArgumentParser) -> None:
        if not self.cli:
            return None
        args = tuple(self.cli)

        help_txt = f"{self.short} [{self.default}]"
        help_txt = help_txt.replace("%", "%%")

        kwargs = {
            "dest": self.name,
            "action": self.action or "store",
            "type": self.type or str,
            "default": None,
            "help": help_txt,
        }

        if self.meta is not None:
            kwargs["metavar"] = self.meta

        if kwargs["action"] != "store":
            kwargs.pop("type")

        if self.nargs is not None:
            kwargs["nargs"] = self.nargs

        if self.const is not None:
            kwargs["const"] = self.const

        parser.add_argument(*args, **kwargs)

    def copy(self) -> Setting:
        return copy.copy(self)

    def get(self) -> Any:
        return self.value

    def set(self, val: Any) -> None:
        if not callable(self.validator):
            raise TypeError(f"Invalid validator: {self.name}")
        self.value = self.validator(val)

    def __lt__(self, other: Setting) -> bool:
        return self.section == other.section and self.order < other.order  # type: ignore[attr-defined]  # order is added by metaclass

    __cmp__ = __lt__

    def __repr__(self) -> str:
        return f"<{self.__class__.__module__}.{self.__class__.__name__} object at {id(self):x} with value {self.value!r}>"


Setting = SettingMeta("Setting", (Setting,), {})  # type: ignore[misc]  # intentional shadowing


def validate_bool(val: Any) -> bool | None:
    if val is None:
        return None

    if isinstance(val, bool):
        return val
    if not isinstance(val, str):
        raise TypeError(f"Invalid type for casting: {val}")
    if val.lower().strip() == "true":
        return True
    elif val.lower().strip() == "false":
        return False
    else:
        raise ValueError(f"Invalid boolean: {val}")


def validate_dict(val: Any) -> dict[str, Any]:
    if not isinstance(val, dict):
        raise TypeError(f"Value is not a dictionary: {val} ")
    return val


def validate_pos_int(val: Any) -> int:
    if not isinstance(val, int):
        val = int(val, 0)
    else:
        # Booleans are ints!
        val = int(val)
    if val < 0:
        raise ValueError(f"Value must be positive: {val}")
    return val


def validate_string(val: Any) -> str | None:
    if val is None:
        return None
    if not isinstance(val, str):
        raise TypeError(f"Not a string: {val}")
    return val.strip()


def validate_file_exists(val: Any) -> str | None:
    if val is None:
        return None
    if not os.path.exists(val):
        raise ValueError(f"File {val} does not exists.")
    return val


def validate_list_string(val: Any) -> list[str]:
    if not val:
        return []

    # legacy syntax
    if isinstance(val, str):
        val = [val]

    return [validate_string(v) for v in val]


def validate_list_of_existing_files(val: Any) -> list[str | None]:
    return [validate_file_exists(v) for v in validate_list_string(val)]


def validate_string_to_addr_list(val: Any) -> list[str]:
    val = validate_string_to_list(val)

    for addr in val:
        if addr == "*":
            continue
        _vaid_ip = ipaddress.ip_address(addr)

    return val


def validate_string_to_list(val: Any) -> list[str]:
    val = validate_string(val)

    if not val:
        return []

    return [v.strip() for v in val.split(",") if v]


def validate_class(val: Any) -> type | str | None:
    if inspect.isfunction(val) or inspect.ismethod(val):
        val = val()
    if inspect.isclass(val):
        return val
    return validate_string(val)


def validate_callable(arity: int) -> Any:
    def _validate_callable(val: Any) -> Any:
        if isinstance(val, str):
            try:
                mod_name, obj_name = val.rsplit(".", 1)
            except ValueError:
                raise TypeError(
                    f"Value '{val}' is not import string. "
                    "Format: module[.submodules...].object"
                )
            try:
                mod = __import__(mod_name, fromlist=[obj_name])
                val = getattr(mod, obj_name)
            except ImportError as e:
                raise TypeError(str(e))
            except AttributeError:
                raise TypeError(f"Can not load '{obj_name}' from '{mod_name}'")
        if not callable(val):
            raise TypeError(f"Value is not callable: {val}")
        if arity != -1 and arity != util.get_arity(val):
            raise TypeError(f"Value must have an arity of: {arity}")
        return val

    return _validate_callable


def validate_reload_engine(val: Any) -> str:
    if val not in reloader_engines:
        raise ConfigError(f"Invalid reload_engine: {val!r}")

    return val


class Bind(Setting):
    name = "bind"
    action = "append"
    section = "Server Socket"
    cli = ["-b", "--bind"]
    meta = "ADDRESS"
    validator = validate_list_string

    if "PORT" in os.environ:
        default = ["0.0.0.0:{}".format(os.environ.get("PORT"))]
    else:
        default = ["127.0.0.1:8000"]

    desc = """\
        The socket to bind.

        A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``,
        ``fd://FD``. An IP is a valid ``HOST``.

        .. versionchanged:: 20.0
           Support for ``fd://FD`` got added.

        Multiple addresses can be bound. ex.::

            $ gunicorn -b 127.0.0.1:8000 -b [::1]:8000 test:app

        will bind the `test:app` application on localhost both on ipv6
        and ipv4 interfaces.

        If the ``PORT`` environment variable is defined, the default
        is ``['0.0.0.0:$PORT']``. If it is not defined, the default
        is ``['127.0.0.1:8000']``.
        """


class Backlog(Setting):
    name = "backlog"
    section = "Server Socket"
    cli = ["--backlog"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 2048
    desc = """\
        The maximum number of pending connections.

        This refers to the number of clients that can be waiting to be served.
        Exceeding this number results in the client getting an error when
        attempting to connect. It should only affect servers under significant
        load.

        Must be a positive integer. Generally set in the 64-2048 range.
        """


class Workers(Setting):
    name = "workers"
    section = "Worker Processes"
    cli = ["-w", "--workers"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = int(os.environ.get("WEB_CONCURRENCY", 1))
    desc = """\
        The number of worker processes for handling requests.

        A positive integer generally in the ``2-4 x $(NUM_CORES)`` range.
        You'll want to vary this a bit to find the best for your particular
        application's work load.

        By default, the value of the ``WEB_CONCURRENCY`` environment variable,
        which is set by some Platform-as-a-Service providers such as Heroku. If
        it is not defined, the default is ``1``.
        """


class WorkerClass(Setting):
    name = "worker_class"
    section = "Worker Processes"
    cli = ["-k", "--worker-class"]
    meta = "STRING"
    validator = validate_class
    default = "sync"
    desc = """\
        The type of workers to use.

        The default class (``sync``) should handle most "normal" types of
        workloads. You'll want to read :doc:`design` for information on when
        you might want to choose one of the other worker classes. Required
        libraries may be installed using setuptools' ``extras_require`` feature.

        A string referring to one of the following bundled classes:

        * ``sync``
        * ``eventlet`` - Requires eventlet >= 0.24.1 (or install it via
          ``pip install gunicorn[eventlet]``)
        * ``gevent``   - Requires gevent >= 1.4 (or install it via
          ``pip install gunicorn[gevent]``)
        * ``tornado``  - Requires tornado >= 0.2 (or install it via
          ``pip install gunicorn[tornado]``)
        * ``gthread``  - Python 2 requires the futures package to be installed
          (or install it via ``pip install gunicorn[gthread]``)

        Optionally, you can provide your own worker by giving Gunicorn a
        Python path to a subclass of ``plain.server.workers.base.Worker``.
        This alternative syntax will load the gevent class:
        ``plain.server.workers.ggevent.GeventWorker``.
        """


class WorkerThreads(Setting):
    name = "threads"
    section = "Worker Processes"
    cli = ["--threads"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 1
    desc = """\
        The number of worker threads for handling requests.

        Run each worker with the specified number of threads.

        A positive integer generally in the ``2-4 x $(NUM_CORES)`` range.
        You'll want to vary this a bit to find the best for your particular
        application's work load.

        If it is not defined, the default is ``1``.

        This setting only affects the Gthread worker type.

        .. note::
           If you try to use the ``sync`` worker type and set the ``threads``
           setting to more than 1, the ``gthread`` worker type will be used
           instead.
        """


class WorkerConnections(Setting):
    name = "worker_connections"
    section = "Worker Processes"
    cli = ["--worker-connections"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 1000
    desc = """\
        The maximum number of simultaneous clients.

        This setting only affects the ``gthread``, ``eventlet`` and ``gevent`` worker types.
        """


class MaxRequests(Setting):
    name = "max_requests"
    section = "Worker Processes"
    cli = ["--max-requests"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 0
    desc = """\
        The maximum number of requests a worker will process before restarting.

        Any value greater than zero will limit the number of requests a worker
        will process before automatically restarting. This is a simple method
        to help limit the damage of memory leaks.

        If this is set to zero (the default) then the automatic worker
        restarts are disabled.
        """


class MaxRequestsJitter(Setting):
    name = "max_requests_jitter"
    section = "Worker Processes"
    cli = ["--max-requests-jitter"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 0
    desc = """\
        The maximum jitter to add to the *max_requests* setting.

        The jitter causes the restart per worker to be randomized by
        ``randint(0, max_requests_jitter)``. This is intended to stagger worker
        restarts to avoid all workers restarting at the same time.

        .. versionadded:: 19.2
        """


class Timeout(Setting):
    name = "timeout"
    section = "Worker Processes"
    cli = ["-t", "--timeout"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 30
    desc = """\
        Workers silent for more than this many seconds are killed and restarted.

        Value is a positive number or 0. Setting it to 0 has the effect of
        infinite timeouts by disabling timeouts for all workers entirely.

        Generally, the default of thirty seconds should suffice. Only set this
        noticeably higher if you're sure of the repercussions for sync workers.
        For the non sync workers it just means that the worker process is still
        communicating and is not tied to the length of time required to handle a
        single request.
        """


class GracefulTimeout(Setting):
    name = "graceful_timeout"
    section = "Worker Processes"
    cli = ["--graceful-timeout"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 30
    desc = """\
        Timeout for graceful workers restart in seconds.

        After receiving a restart signal, workers have this much time to finish
        serving requests. Workers still alive after the timeout (starting from
        the receipt of the restart signal) are force killed.
        """


class Keepalive(Setting):
    name = "keepalive"
    section = "Worker Processes"
    cli = ["--keep-alive"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 2
    desc = """\
        The number of seconds to wait for requests on a Keep-Alive connection.

        Generally set in the 1-5 seconds range for servers with direct connection
        to the client (e.g. when you don't have separate load balancer). When
        Gunicorn is deployed behind a load balancer, it often makes sense to
        set this to a higher value.

        .. note::
           ``sync`` worker does not support persistent connections and will
           ignore this option.
        """


class LimitRequestLine(Setting):
    name = "limit_request_line"
    section = "Security"
    cli = ["--limit-request-line"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 4094
    desc = """\
        The maximum size of HTTP request line in bytes.

        This parameter is used to limit the allowed size of a client's
        HTTP request-line. Since the request-line consists of the HTTP
        method, URI, and protocol version, this directive places a
        restriction on the length of a request-URI allowed for a request
        on the server. A server needs this value to be large enough to
        hold any of its resource names, including any information that
        might be passed in the query part of a GET request. Value is a number
        from 0 (unlimited) to 8190.

        This parameter can be used to prevent any DDOS attack.
        """


class LimitRequestFields(Setting):
    name = "limit_request_fields"
    section = "Security"
    cli = ["--limit-request-fields"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 100
    desc = """\
        Limit the number of HTTP headers fields in a request.

        This parameter is used to limit the number of headers in a request to
        prevent DDOS attack. Used with the *limit_request_field_size* it allows
        more safety. By default this value is 100 and can't be larger than
        32768.
        """


class LimitRequestFieldSize(Setting):
    name = "limit_request_field_size"
    section = "Security"
    cli = ["--limit-request-field_size"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 8190
    desc = """\
        Limit the allowed size of an HTTP request header field.

        Value is a positive number or 0. Setting it to 0 will allow unlimited
        header field sizes.

        .. warning::
           Setting this parameter to a very high or unlimited value can open
           up for DDOS attacks.
        """


class Reload(Setting):
    name = "reload"
    section = "Debugging"
    cli = ["--reload"]
    validator = validate_bool
    action = "store_true"
    default = False

    desc = """\
        Restart workers when code changes.

        This setting is intended for development. It will cause workers to be
        restarted whenever application code changes.

        The reloader is incompatible with application preloading. When using a
        paste configuration be sure that the server block does not import any
        application code or the reload will not work as designed.

        The default behavior is to attempt inotify with a fallback to file
        system polling. Generally, inotify should be preferred if available
        because it consumes less system resources.

        .. note::
           In order to use the inotify reloader, you must have the ``inotify``
           package installed.
        """


class ReloadEngine(Setting):
    name = "reload_engine"
    section = "Debugging"
    cli = ["--reload-engine"]
    meta = "STRING"
    validator = validate_reload_engine
    default = "auto"
    desc = """\
        The implementation that should be used to power :ref:`reload`.

        Valid engines are:

        * ``'auto'``
        * ``'poll'``
        * ``'inotify'`` (requires inotify)

        .. versionadded:: 19.7
        """


class ReloadExtraFiles(Setting):
    name = "reload_extra_files"
    action = "append"
    section = "Debugging"
    cli = ["--reload-extra-file"]
    meta = "FILES"
    validator = validate_list_of_existing_files
    default = []
    desc = """\
        Extends :ref:`reload` option to also watch and reload on additional files
        (e.g., templates, configurations, specifications, etc.).

        .. versionadded:: 19.8
        """


class Sendfile(Setting):
    name = "sendfile"
    section = "Server Mechanics"
    cli = ["--no-sendfile"]
    validator = validate_bool
    action = "store_const"
    const = False

    desc = """\
        Disables the use of ``sendfile()``.

        If not set, the value of the ``SENDFILE`` environment variable is used
        to enable or disable its usage.

        .. versionadded:: 19.2
        .. versionchanged:: 19.4
           Swapped ``--sendfile`` with ``--no-sendfile`` to actually allow
           disabling.
        .. versionchanged:: 19.6
           added support for the ``SENDFILE`` environment variable
        """


class ReusePort(Setting):
    name = "reuse_port"
    section = "Server Mechanics"
    cli = ["--reuse-port"]
    validator = validate_bool
    action = "store_true"
    default = False

    desc = """\
        Set the ``SO_REUSEPORT`` flag on the listening socket.

        .. versionadded:: 19.8
        """


class Pidfile(Setting):
    name = "pidfile"
    section = "Server Mechanics"
    cli = ["-p", "--pid"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        A filename to use for the PID file.

        If not set, no PID file will be written.
        """


class SecureSchemeHeader(Setting):
    name = "secure_scheme_headers"
    section = "Server Mechanics"
    validator = validate_dict
    default = {
        "X-FORWARDED-PROTOCOL": "ssl",
        "X-FORWARDED-PROTO": "https",
        "X-FORWARDED-SSL": "on",
    }
    desc = """\

        A dictionary containing headers and values that the front-end proxy
        uses to indicate HTTPS requests. If the source IP is permitted by
        :ref:`forwarded-allow-ips` (below), *and* at least one request header matches
        a key-value pair listed in this dictionary, then Gunicorn will set
        ``wsgi.url_scheme`` to ``https``, so your application can tell that the
        request is secure.

        If the other headers listed in this dictionary are not present in the request, they will be ignored,
        but if the other headers are present and do not match the provided values, then
        the request will fail to parse. See the note below for more detailed examples of this behaviour.

        The dictionary should map upper-case header names to exact string
        values. The value comparisons are case-sensitive, unlike the header
        names, so make sure they're exactly what your front-end proxy sends
        when handling HTTPS requests.

        It is important that your front-end proxy configuration ensures that
        the headers defined here can not be passed directly from the client.
        """


class ForwardedAllowIPS(Setting):
    name = "forwarded_allow_ips"
    section = "Server Mechanics"
    cli = ["--forwarded-allow-ips"]
    meta = "STRING"
    validator = validate_string_to_addr_list
    default = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    desc = """\
        Front-end's IPs from which allowed to handle set secure headers.
        (comma separated).

        Set to ``*`` to disable checking of front-end IPs. This is useful for setups
        where you don't know in advance the IP address of front-end, but
        instead have ensured via other means that only your
        authorized front-ends can access Gunicorn.

        By default, the value of the ``FORWARDED_ALLOW_IPS`` environment
        variable. If it is not defined, the default is ``"127.0.0.1,::1"``.

        .. note::

            This option does not affect UNIX socket connections. Connections not associated with
            an IP address are treated as allowed, unconditionally.

        .. note::

            The interplay between the request headers, the value of ``forwarded_allow_ips``, and the value of
            ``secure_scheme_headers`` is complex. Various scenarios are documented below to further elaborate.
            In each case, we have a request from the remote address 134.213.44.18, and the default value of
            ``secure_scheme_headers``:

            .. code::

                secure_scheme_headers = {
                    'X-FORWARDED-PROTOCOL': 'ssl',
                    'X-FORWARDED-PROTO': 'https',
                    'X-FORWARDED-SSL': 'on'
                }


            .. list-table::
                :header-rows: 1
                :align: center
                :widths: auto

                * - ``forwarded-allow-ips``
                  - Secure Request Headers
                  - Result
                  - Explanation
                * - .. code::

                        ["127.0.0.1"]
                  - .. code::

                        X-Forwarded-Proto: https
                  - .. code::

                        wsgi.url_scheme = "http"
                  - IP address was not allowed
                * - .. code::

                        "*"
                  - <none>
                  - .. code::

                        wsgi.url_scheme = "http"
                  - IP address allowed, but no secure headers provided
                * - .. code::

                        "*"
                  - .. code::

                        X-Forwarded-Proto: https
                  - .. code::

                        wsgi.url_scheme = "https"
                  - IP address allowed, one request header matched
                * - .. code::

                        ["134.213.44.18"]
                  - .. code::

                        X-Forwarded-Ssl: on
                        X-Forwarded-Proto: http
                  - ``InvalidSchemeHeaders()`` raised
                  - IP address allowed, but the two secure headers disagreed on if HTTPS was used


        """


class AccessLog(Setting):
    name = "accesslog"
    section = "Logging"
    cli = ["--access-logfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        The Access log file to write to.

        ``'-'`` means log to stdout.
        """


class AccessLogFormat(Setting):
    name = "access_log_format"
    section = "Logging"
    cli = ["--access-logformat"]
    meta = "STRING"
    validator = validate_string
    default = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
    desc = """\
        The access log format.

        ===========  ===========
        Identifier   Description
        ===========  ===========
        h            remote address
        l            ``'-'``
        u            user name (if HTTP Basic auth used)
        t            date of the request
        r            status line (e.g. ``GET / HTTP/1.1``)
        m            request method
        U            URL path without query string
        q            query string
        H            protocol
        s            status
        B            response length
        b            response length or ``'-'`` (CLF format)
        f            referrer (note: header is ``referer``)
        a            user agent
        T            request time in seconds
        M            request time in milliseconds
        D            request time in microseconds
        L            request time in decimal seconds
        p            process ID
        {header}i    request header
        {header}o    response header
        {variable}e  environment variable
        ===========  ===========

        Use lowercase for header and environment variable names, and put
        ``{...}x`` names inside ``%(...)s``. For example::

            %({x-forwarded-for}i)s
        """


class ErrorLog(Setting):
    name = "errorlog"
    section = "Logging"
    cli = ["--error-logfile", "--log-file"]
    meta = "FILE"
    validator = validate_string
    default = "-"
    desc = """\
        The Error log file to write to.

        Using ``'-'`` for FILE makes gunicorn log to stderr.

        .. versionchanged:: 19.2
           Log to stderr by default.

        """


class Loglevel(Setting):
    name = "loglevel"
    section = "Logging"
    cli = ["--log-level"]
    meta = "LEVEL"
    validator = validate_string
    default = "info"
    desc = """\
        The granularity of Error log outputs.

        Valid level names are:

        * ``'debug'``
        * ``'info'``
        * ``'warning'``
        * ``'error'``
        * ``'critical'``
        """


class CaptureOutput(Setting):
    name = "capture_output"
    section = "Logging"
    cli = ["--capture-output"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Redirect stdout/stderr to specified file in :ref:`errorlog`.

        .. versionadded:: 19.6
        """


class LoggerClass(Setting):
    name = "logger_class"
    section = "Logging"
    cli = ["--logger-class"]
    meta = "STRING"
    validator = validate_class
    default = "plain.server.glogging.Logger"
    desc = """\
        The logger you want to use to log events in Gunicorn.

        The default class (``plain.server.glogging.Logger``) handles most
        normal usages in logging. It provides error and access logging.

        You can provide your own logger by giving Gunicorn a Python path to a
        class that quacks like ``plain.server.glogging.Logger``.
        """


class LogConfig(Setting):
    name = "logconfig"
    section = "Logging"
    cli = ["--log-config"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    The log config file to use.
    Gunicorn uses the standard Python logging module's Configuration
    file format.
    """


class LogConfigDict(Setting):
    name = "logconfig_dict"
    section = "Logging"
    validator = validate_dict
    default = {}
    desc = """\
    The log config dictionary to use, using the standard Python
    logging module's dictionary configuration format. This option
    takes precedence over the :ref:`logconfig` and :ref:`logconfig-json` options,
    which uses the older file configuration format and JSON
    respectively.

    Format: https://docs.python.org/3/library/logging.config.html#logging.config.dictConfig

    For more context you can look at the default configuration dictionary for logging,
    which can be found at ``plain.server.glogging.CONFIG_DEFAULTS``.

    .. versionadded:: 19.8
    """


class LogConfigJson(Setting):
    name = "logconfig_json"
    section = "Logging"
    cli = ["--log-config-json"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    The log config to read config from a JSON file

    Format: https://docs.python.org/3/library/logging.config.html#logging.config.jsonConfig

    .. versionadded:: 20.0
    """


class Procname(Setting):
    name = "proc_name"
    section = "Process Naming"
    cli = ["-n", "--name"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        A base to use with setproctitle for process naming.

        This affects things like ``ps`` and ``top``. If you're going to be
        running more than one instance of Gunicorn you'll probably want to set a
        name to tell them apart. This requires that you install the setproctitle
        module.

        If not set, the *default_proc_name* setting will be used.
        """


class DefaultProcName(Setting):
    name = "default_proc_name"
    section = "Process Naming"
    validator = validate_string
    default = "gunicorn"
    desc = """\
        Internal setting that is adjusted for each type of application.
        """


class NewSSLContext(Setting):
    name = "ssl_context"
    section = "Server Hooks"
    validator = validate_callable(2)
    type = callable

    def ssl_context(config: Any, default_ssl_context_factory: Any) -> Any:
        return default_ssl_context_factory()

    default = staticmethod(ssl_context)
    desc = """\
        Called when SSLContext is needed.

        Allows customizing SSL context.

        The callable needs to accept an instance variable for the Config and
        a factory function that returns default SSLContext which is initialized
        with certificates, private key, cert_reqs, and ciphers according to
        config and can be further customized by the callable.
        The callable needs to return SSLContext object.

        Following example shows a configuration file that sets the minimum TLS version to 1.3:

        .. code-block:: python

            def ssl_context(conf, default_ssl_context_factory):
                import ssl
                context = default_ssl_context_factory()
                context.minimum_version = ssl.TLSVersion.TLSv1_3
                return context

        .. versionadded:: 21.0
        """


class KeyFile(Setting):
    name = "keyfile"
    section = "SSL"
    cli = ["--keyfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    SSL key file
    """


class CertFile(Setting):
    name = "certfile"
    section = "SSL"
    cli = ["--certfile"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    SSL certificate file
    """


def validate_header_map_behaviour(val: Any) -> str | None:
    # FIXME: refactor all of this subclassing stdlib argparse

    if val is None:
        return None

    if not isinstance(val, str):
        raise TypeError(f"Invalid type for casting: {val}")
    if val.lower().strip() == "drop":
        return "drop"
    elif val.lower().strip() == "refuse":
        return "refuse"
    elif val.lower().strip() == "dangerous":
        return "dangerous"
    else:
        raise ValueError(f"Invalid header map behaviour: {val}")


class ForwarderHeaders(Setting):
    name = "forwarder_headers"
    section = "Server Mechanics"
    cli = ["--forwarder-headers"]
    validator = validate_string_to_list
    default = "SCRIPT_NAME,PATH_INFO"
    desc = """\

        A list containing upper-case header field names that the front-end proxy
        (see :ref:`forwarded-allow-ips`) sets, to be used in WSGI environment.

        This option has no effect for headers not present in the request.

        This option can be used to transfer ``SCRIPT_NAME``, ``PATH_INFO``
        and ``REMOTE_USER``.

        It is important that your front-end proxy configuration ensures that
        the headers defined here can not be passed directly from the client.
        """


class HeaderMap(Setting):
    name = "header_map"
    section = "Server Mechanics"
    cli = ["--header-map"]
    validator = validate_header_map_behaviour
    default = "drop"
    desc = """\
        Configure how header field names are mapped into environ

        Headers containing underscores are permitted by RFC9110,
        but gunicorn joining headers of different names into
        the same environment variable will dangerously confuse applications as to which is which.

        The safe default ``drop`` is to silently drop headers that cannot be unambiguously mapped.
        The value ``refuse`` will return an error if a request contains *any* such header.
        The value ``dangerous`` matches the previous, not advisable, behaviour of mapping different
        header field names into the same environ name.

        If the source is permitted as explained in :ref:`forwarded-allow-ips`, *and* the header name is
        present in :ref:`forwarder-headers`, the header is mapped into environment regardless of
        the state of this setting.

        Use with care and only if necessary and after considering if your problem could
        instead be solved by specifically renaming or rewriting only the intended headers
        on a proxy in front of Gunicorn.

        .. versionadded:: 22.0.0
        """
