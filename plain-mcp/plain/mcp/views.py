from __future__ import annotations

import base64
import json
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, ClassVar

from opentelemetry import trace
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from plain.http import (
    JsonResponse,
    Response,
    status_for_exception,
)
from plain.logs import get_framework_logger, log_exception
from plain.runtime import settings
from plain.utils.otel import format_exception_type
from plain.views.base import View

from .exceptions import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
    MCPInvalidParams,
    MCPToolError,
    MCPUnauthorized,
    _error_response,
    _ProtocolError,
)
from .resources import MCPResource
from .schema import validate_arguments
from .tools import MCPTool

tracer = trace.get_tracer("plain.mcp")

logger = get_framework_logger()

# The revision this server speaks natively. 2026-07-28 is stateless — no
# sessions, no `initialize` handshake, no server-to-client stream.
PROTOCOL_VERSION = "2026-07-28"

# Earlier revisions, still served for clients that open with `initialize` —
# claude.ai's connector proxy among them, as of mid-2026. They reach the same
# handlers through a compatibility branch in `post()`; see
# `handle_classic_message`. Newest first: that's the counter-offer to a client
# whose requested version isn't listed, per the classic negotiation rule.
CLASSIC_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# Keys inside `params._meta`. protocolVersion and clientCapabilities are
# required on every request (they replace what the handshake used to
# establish once); clientInfo is optional.
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"

# Key inside a result's `_meta`, naming the server that produced it.
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# The HTTP status an in-band JSON-RPC reply travels at, keyed by its error
# code. One table decides it wherever the error came from — the validation
# ladder or a handler — so a code never rides two different statuses. Every
# code plain.mcp raises is listed, INTERNAL_ERROR included: a server-side
# failure isn't a malformed request, so it rides a 200 like a success. A code
# missing from here silently falls back to 200, so add new ones as you define
# them.
#
# Framework exceptions (LoginRequired, an HTTPException from a view) don't come
# through here at all — `handle_exception` is a separate funnel where the HTTP
# status leads and the JSON-RPC code follows from it.
ERROR_CODE_HTTP_STATUS: dict[int, int] = {
    PARSE_ERROR: 400,
    INVALID_REQUEST: 400,
    INVALID_PARAMS: 400,
    HEADER_MISMATCH: 400,
    MISSING_REQUIRED_CLIENT_CAPABILITY: 400,
    UNSUPPORTED_PROTOCOL_VERSION: 400,
    METHOD_NOT_FOUND: 404,
    INTERNAL_ERROR: 200,
}

# The other direction, for `handle_exception`: 400 and 500 have standard
# JSON-RPC codes, and for every other status the status itself is the code. The
# reserved -320xx range belongs to the protocol — -32001 is a request timeout
# there — so borrowing it for auth would have clients read a 401 as a timeout.
# The real auth signal is the HTTP status plus `WWW-Authenticate`.
_STATUS_TO_JSON_RPC_CODE: dict[int, int] = {
    400: INVALID_PARAMS,
    500: INTERNAL_ERROR,
}


def _header_mismatch(detail: str) -> _ProtocolError:
    """The transport's one failure mode: a header that's missing or disagrees."""
    return _ProtocolError(HEADER_MISMATCH, f"Header mismatch: {detail}")


class MCPView(View):
    """An MCP server endpoint. Subclass to build your own.

    `MCPView` is a Plain View — mount it in your URLs directly:

        class AppMCP(MCPView):
            name = "myapp"
            tools = [Greet]

        # app/urls.py
        path("mcp", AppMCP, name="mcp")

    MCPView itself does no authentication. Compose with `plain.auth.views.AuthView`
    for session auth (put `MCPView` first in the base list), or override
    `before_request()` to verify a token / custom credentials and raise
    `MCPUnauthorized` on failure. The raised exception is translated to a
    JSON-RPC 401 response by `handle_exception`.

    Register tools declaratively on the class:

        class AppMCP(MCPView):
            name = "myapp"
            tools = [Greet, Search]

    Or imperatively, which is how third-party packages attach to a shared
    MCPView they don't own (e.g. `plain.admin.mcp.AdminMCP`):

        AdminMCP.register_tool(PageViewStats)

    Handling JSON-RPC methods beyond the tools capability: define a method
    named `rpc_<method>` where slashes in the JSON-RPC method become
    underscores. Advertise the matching capability by overriding
    `get_capabilities()`:

        class AppMCP(MCPView):
            def rpc_prompts_list(self, params):
                return {"prompts": [...]}

            def get_capabilities(self):
                caps = super().get_capabilities()
                caps["prompts"] = {}
                return caps
    """

    name: str = ""
    version: str = ""

    # Natural-language guidance for the LLM driving this server — how to use
    # these tools, what the app is for. Returned by `server/discover` when set.
    instructions: str = ""

    tools: tuple[type[MCPTool], ...] = ()
    resources: tuple[type[MCPResource], ...] = ()

    # Methods whose results are `CacheableResult`s — the spec requires a
    # freshness hint (`ttlMs`) and a `cacheScope` on every one of them. Add
    # your own `rpc_` list methods here to have them stamped too.
    cacheable_result_methods: frozenset[str] = frozenset(
        {
            "server/discover",
            "tools/list",
            "prompts/list",
            "resources/list",
            "resources/templates/list",
            "resources/read",
        }
    )

    # Methods where the `Mcp-Name` header mirrors a body param, and which
    # param it mirrors. Everything else sends no `Mcp-Name`. Add your own
    # target-naming methods here to have the header checked for them too.
    name_header_params: ClassVar[dict[str, str]] = {
        "tools/call": "name",
        "prompts/get": "name",
        "resources/read": "uri",
    }

    # Who is calling, read from the current request's `_meta`. Tools reach
    # these through `self.mcp`.
    client_info: dict[str, Any] | None = None
    client_capabilities: dict[str, Any] = {}  # noqa: RUF012 — replaced per-instance, never mutated

    # The routing facts `post()` has learned about the current request —
    # each one is stamped onto the request span as an `mcp.<key>` attribute
    # the moment it's known, and repeated in the reject log's context. A
    # request that dies on the validation ladder carries whatever was known
    # by then, which is exactly what a "why was this client rejected?"
    # investigation needs.
    _routing_facts: dict[str, Any] = {}  # noqa: RUF012 — replaced per-instance, never mutated

    @classmethod
    def register_tool(cls, tool_cls: type[MCPTool]) -> type[MCPTool]:
        """Attach a tool to this MCPView subclass.

        Used by third-party packages to extend a shared MCPView subclass
        (e.g. `plain.admin.mcp.AdminMCP`) that they don't own:

            AdminMCP.register_tool(PageViewStats)
        """
        cls._append_unique("tools", tool_cls)
        return tool_cls

    @classmethod
    def register_resource(cls, resource_cls: type[MCPResource]) -> type[MCPResource]:
        """Attach a resource to this MCPView subclass. Parallels `register_tool`."""
        cls._append_unique("resources", resource_cls)
        return resource_cls

    @classmethod
    def _append_unique(cls, attr: str, item: type) -> None:
        # Rebuild the tuple on this class so registrations don't bleed into
        # the base class or sibling subclasses.
        existing = tuple(getattr(cls, attr))
        if item not in existing:
            setattr(cls, attr, (*existing, item))

    def get_tools(self) -> list[type[MCPTool]]:
        """Return the tools available for this request.

        Default: the class-level `tools` list, filtered through each
        tool's `allowed_for(self)` classmethod. Override to skip per-tool
        gates (e.g. superuser bypass) or to add dynamic tools. Returned
        list must not be mutated by callers.
        """
        return [t for t in self.tools if t.allowed_for(self)]

    def get_resources(self) -> list[type[MCPResource]]:
        """Return the resources available for this request.

        Default: the class-level `resources` list, filtered through each
        resource's `allowed_for(self)` classmethod. Override to skip
        per-resource gates or to add dynamic resources.
        """
        return [r for r in self.resources if r.allowed_for(self)]

    def handle_exception(self, exc: Exception) -> Response:
        """Translate framework exceptions into JSON-RPC responses.

        MCP clients expect JSON bodies and can't follow HTTP redirects, so
        we catch the standard auth/routing exceptions here and emit
        JSON-RPC error objects at appropriate status codes.
        """
        headers = None

        if isinstance(exc, MCPUnauthorized):
            status = 401
            message = str(exc) or "Unauthorized"
            if exc.www_authenticate:
                headers = {"WWW-Authenticate": exc.www_authenticate}
        else:
            status = status_for_exception(exc)
            if status >= 500:
                message = "Internal error"
            else:
                message = str(exc) or HTTPStatus(status).phrase

        return JsonResponse(
            _error_response(
                None, _STATUS_TO_JSON_RPC_CODE.get(status, status), message
            ),
            status_code=status,
            headers=headers,
        )

    def post(self) -> Response:
        """One POST carries exactly one JSON-RPC request or notification.

        Which revision family the request belongs to is settled right after
        it's read: a 2026-07-28 request declares its protocol version inside
        `params._meta` on every message, and a request without that
        declaration is from the classic, handshake-era protocol and takes
        the compatibility branch instead (`handle_classic_message`) — unless
        its `MCP-Protocol-Version` header explicitly names `2026-07-28`,
        which is a modern client whose envelope needs diagnosing. Other
        header facts don't participate in the decision.

        On the modern path, whether the method exists is settled first — a
        method nobody implements can't be judged by an envelope. Then comes
        the validation ladder, in order: the request must say what it is
        (`_meta`), then agree with itself (headers), then speak a version we
        have. A client that contradicts itself is told that before it's told
        its version is unsupported — the two answers call for different
        fixes.

        There is no GET stream and no session — GET and DELETE fall through
        to the base view's 405. That answer is legal in every revision served
        here: the classic Streamable HTTP transport lets a server decline the
        GET stream with a 405 and issue no session id.
        """
        # Fresh per request — the class attribute is only the fallback for
        # code paths that never went through here.
        self._routing_facts = {}
        if version_header := self.request.headers.get("MCP-Protocol-Version"):
            self._stamp_routing_fact("protocol_version_header", version_header)
        self._stamp_routing_fact(
            "method_header_present", "Mcp-Method" in self.request.headers
        )

        msg_id: Any = None
        try:
            message = _decode_request(self.request.body)

            # Read out before anything that can fail below, so every error from
            # here down carries the id the client correlates its reply by.
            msg_id = message.get("id")

            method = _read_method(message)
            self._stamp_routing_fact("method", method)

            if msg_id is None:
                # Spec MUST: a notification (no `id`) is acknowledged with 202
                # and no body — never a reply, not even an error one, so its
                # params go unchecked. The spec leaves header requirements for
                # notifications undefined, so nothing further is checked either.
                return Response(status_code=202)

            params = _read_params(message)

            # Which family is this request from? The modern envelope's own
            # structural marker decides: a 2026-07-28 request restates its
            # protocol version in `params._meta` on every message, so a
            # request carrying that key is modern outright. Without it,
            # `initialize` is always classic — the modern revision removed
            # the method, so nothing but a classic handshake opens with it —
            # and for everything else only an `MCP-Protocol-Version` header
            # naming `2026-07-28` exactly, the client's own declaration that
            # it speaks the modern revision, selects the modern ladder: that
            # keeps a conformant modern client with a broken envelope told
            # precisely which field is missing (the spec's conformance suite
            # requires that diagnosis). No other header fact gets a vote.
            # HTTP semantics make unrecognized headers fair game for any
            # client, SDK, or middlebox, so a header's presence is not
            # evidence of a revision — a conformant 2025-11-25 client that
            # also sent `Mcp-Method` was once misrouted here and rejected
            # mid-session for a `_meta` envelope its revision never defined.
            meta = params.get("_meta")
            meta_declares_modern = (
                isinstance(meta, dict) and META_PROTOCOL_VERSION in meta
            )
            if meta_declares_modern:
                is_classic = False
            elif method == "initialize":
                is_classic = True
            else:
                is_classic = (
                    self.request.headers.get("MCP-Protocol-Version") != PROTOCOL_VERSION
                )
            self._stamp_routing_fact(
                "meta_protocol_version_present", meta_declares_modern
            )
            self._stamp_routing_fact("revision", "classic" if is_classic else "modern")
            if is_classic:
                return self.handle_classic_message(
                    msg_id=msg_id, method=method, params=params
                )

            # Resolved here, at the rung that decides it, and carried down to
            # dispatch — `get_rpc_handler` is an overridable seam, so it runs
            # exactly once per request.
            handler = self.get_rpc_handler(method)

            protocol_version = self.load_client_identity(params)
            self.check_request_headers(
                method=method, params=params, protocol_version=protocol_version
            )

            if protocol_version != PROTOCOL_VERSION:
                # Last rung. `protocol_version` is a string by now, and
                # `requested` has to stay one — this is the one code an
                # auto-negotiating client can't fall back from, so a null
                # there breaks its whole recovery path.
                raise _ProtocolError(
                    UNSUPPORTED_PROTOCOL_VERSION,
                    f"Unsupported protocol version: {protocol_version}",
                    data={
                        "supported": [PROTOCOL_VERSION],
                        "requested": protocol_version,
                    },
                )

            reply = self.handle_message(
                msg_id=msg_id, method=method, params=params, handler=handler
            )
        except _ProtocolError as e:
            reply = e.as_response(msg_id)

        self._observe_reply_error(reply)
        error = reply.get("error")
        status_code = ERROR_CODE_HTTP_STATUS.get(error["code"], 200) if error else 200
        return JsonResponse(reply, status_code=status_code)

    def handle_classic_message(
        self, *, msg_id: Any, method: str, params: dict[str, Any]
    ) -> Response:
        """Serve one request from a pre-2026-07-28 client.

        The classic revisions establish identity once, in an `initialize`
        handshake, and mirror nothing into headers — so none of the modern
        validation ladder applies. Dispatch lands on the same `rpc_` handlers;
        `initialize` and `ping` — the methods the modern revision removed —
        are answered here directly.

        Two deliberate departures from a full classic server, both
        spec-permitted, keep this branch stateless:

        - No `Mcp-Session-Id` is ever issued, so there is no session to
          resume, stream, or delete.
        - Nothing from `initialize` is remembered. Capabilities a classic
          client declares there are gone by its next request, so tools with
          `required_client_capabilities` refuse classic clients.

        Every reply — errors included — travels at HTTP 200: the spec-mandated
        error statuses in `ERROR_CODE_HTTP_STATUS` are 2026-07-28 vocabulary,
        and a classic client reads the JSON-RPC error from the body. (A 404 on
        `initialize` is exactly what sends one chasing the deprecated SSE
        transport.)

        Delete this branch once the clients that matter speak 2026-07-28.
        """
        try:
            if method == "initialize":
                handler = self.classic_initialize_result
            elif method == "ping":
                handler = self.classic_ping_result
            else:
                try:
                    handler = self.get_rpc_handler(method)
                except _ProtocolError as e:
                    if e.code != METHOD_NOT_FOUND:
                        raise
                    # The modern resolver's unknown-method error names
                    # 2026-07-28 — to a client that just negotiated a classic
                    # version, that reads as a version mismatch and can tear
                    # down a session that's actually fine. Same code, no
                    # version claim.
                    raise _ProtocolError(
                        METHOD_NOT_FOUND, f"Unknown method: {method}"
                    ) from None
            # Through `handle_message` even for initialize/ping, so every
            # classic dispatch gets the same `rpc <method>` span and
            # handler-failure funnel (-32603 in the body, logged) as a modern
            # one. `stamp=False`: `resultType`, `serverInfo`, and the
            # freshness hints are 2026-07-28 vocabulary a classic client
            # never asked for.
            reply = self.handle_message(
                msg_id=msg_id,
                method=method,
                params=params,
                handler=handler,
                stamp=False,
            )
        except _ProtocolError as e:
            reply = e.as_response(msg_id)
        self._observe_reply_error(reply)
        return JsonResponse(reply, status_code=200)

    def classic_initialize_result(self, params: dict[str, Any]) -> dict[str, Any]:
        """The `initialize` result, built by the classic negotiation rule.

        A requested version we serve is echoed back; anything else — older,
        newer, or absent — is answered with our newest classic revision, and
        the client decides whether it can work with that.
        """
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in CLASSIC_PROTOCOL_VERSIONS
            else CLASSIC_PROTOCOL_VERSIONS[0]
        )

        result: dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": self.get_capabilities(),
            "serverInfo": {
                "name": self.name,
                "version": self.version or settings.VERSION,
            },
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def classic_ping_result(self, params: dict[str, Any]) -> dict[str, Any]:
        """Classic `ping` answers an empty result. Not named `rpc_ping` on
        purpose — that would resurrect `ping` on the modern path, where the
        spec removed it."""
        return {}

    def _stamp_routing_fact(self, key: str, value: str | bool) -> None:
        """Record one routing fact: on the request span, and for the reject log."""
        self._routing_facts[key] = value
        trace.get_current_span().set_attribute(f"mcp.{key}", value)

    def _observe_reply_error(self, reply: dict[str, Any]) -> None:
        """Make a JSON-RPC error reply visible server-side before it ships.

        The body tells the client exactly what's wrong, but a client that
        swallows it surfaces nothing better than "connection failed" — so the
        code and message also land on the request span, and everything except
        an internal error logs a warning carrying the routing facts. Internal
        errors are excluded because `handle_message` already logged them with
        a traceback.
        """
        error = reply.get("error")
        if not error:
            return
        span = trace.get_current_span()
        span.set_attribute("mcp.error.code", error["code"])
        span.set_attribute("mcp.error.message", error["message"])
        if error["code"] == INTERNAL_ERROR:
            return
        logger.warning(
            "MCP request rejected",
            extra={
                "error_code": error["code"],
                "error_message": error["message"],
                **self._routing_facts,
            },
        )

    def load_client_identity(self, params: dict[str, Any]) -> str:
        """Read the required per-request `_meta`, and return its protocol version.

        Every request restates its protocol version and the client's
        capabilities — there is no handshake to establish them once. This is
        the presence-and-shape rung only: whether we *speak* the version it
        names is decided later, after the headers have been checked against it.
        """
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            meta = {}

        version = meta.get(META_PROTOCOL_VERSION)
        if not isinstance(version, str):
            raise _ProtocolError(
                INVALID_PARAMS,
                f"Missing required params._meta['{META_PROTOCOL_VERSION}']",
            )

        capabilities = meta.get(META_CLIENT_CAPABILITIES)
        if not isinstance(capabilities, dict):
            raise _ProtocolError(
                INVALID_PARAMS,
                f"Missing required params._meta['{META_CLIENT_CAPABILITIES}']",
            )

        client_info = meta.get(META_CLIENT_INFO)
        self.client_capabilities = capabilities
        self.client_info = client_info if isinstance(client_info, dict) else None
        return version

    def check_request_headers(
        self, *, method: str, params: dict[str, Any], protocol_version: str
    ) -> None:
        """Verify the transport headers mirror the JSON-RPC body.

        The transport requires `MCP-Protocol-Version` and `Mcp-Method` on
        every request, plus `Mcp-Name` on the methods that name a target, so
        infrastructure in front of the server can route and authorize without
        parsing the body. A missing or disagreeing header is a transport
        failure — `HeaderMismatch` at HTTP 400.
        """
        for header, body_value in (
            ("MCP-Protocol-Version", protocol_version),
            ("Mcp-Method", method),
        ):
            header_value = self.request.headers.get(header)
            if not header_value:
                raise _header_mismatch(f"{header} header is required")
            if header_value != body_value:
                raise _header_mismatch(
                    f"{header} header value '{header_value}' "
                    f"does not match body value '{body_value}'"
                )

        name_param = self.name_header_params.get(method)
        if name_param is None:
            return

        body_name = params.get(name_param)
        if not body_name:
            # Nothing in the body for the header to mirror. That's a missing
            # parameter, not a header problem — let dispatch say so, using the
            # same "falsy means absent" test the handlers use.
            return

        header_name = self.request.headers.get("Mcp-Name")
        if header_name is None:
            raise _header_mismatch(f"Mcp-Name header is required for {method}")

        decoded_name = _decode_header_value(header_name)
        if decoded_name != body_name:
            raise _header_mismatch(
                f"Mcp-Name header value '{decoded_name}' "
                f"does not match body value '{body_name}'"
            )

    def get_rpc_handler(
        self, method: str
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Find the `rpc_<method>` handler, with `/` in the method written as `_`."""
        # Reject `_` in the method name so the `/` → `_` rewrite can't be
        # spoofed by a client sending `tools_list` instead of `tools/list`.
        if "_" not in method:
            handler = getattr(self, f"rpc_{method.replace('/', '_')}", None)
            if handler is not None:
                return handler

        # Spec MUST: an unknown method answers 404 carrying the JSON-RPC error.
        # That pairing is what tells a client it reached a modern MCP server
        # rather than a URL that doesn't exist. On the modern path, the methods
        # this revision removed — `initialize`, `ping`, `logging/setLevel` —
        # land here too (SEP-2575), so the answer names the version we speak.
        # A *classic* client's `initialize` never gets here: it carries no
        # modern envelope, so `post()` routes it to the compatibility branch.
        # (The classic branch reuses this resolver for its other methods and
        # returns this same error at HTTP 200.)
        raise _ProtocolError(
            METHOD_NOT_FOUND,
            f"Unknown method: {method}. This server speaks MCP {PROTOCOL_VERSION}.",
            data={"supportedVersions": [PROTOCOL_VERSION]},
        )

    def handle_message(
        self,
        *,
        msg_id: Any,
        method: str,
        params: dict[str, Any],
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        stamp: bool = True,
    ) -> dict[str, Any]:
        """Dispatch one validated request to its `rpc_<method>` handler.

        `post()` resolves the handler before the validation ladder runs and
        passes it in — `method` still comes along, for the span name and for
        `stamp_result`. Returns the JSON-RPC reply, success or error alike;
        `post()` maps the reply's error code through `ERROR_CODE_HTTP_STATUS`
        to decide what status it travels at. The classic branch passes
        `stamp=False` — the stamped fields are 2026-07-28 vocabulary.
        """
        with tracer.start_as_current_span(
            f"rpc {method}", kind=trace.SpanKind.SERVER
        ) as span:
            try:
                result = handler(params)
                # Say what a handler got wrong, on both revision paths.
                # Without these, a handler returning None or a list either
                # fails on `dict(...)` in `stamp_result` under an opaque
                # "argument must be a mapping", or — unstamped — ships the
                # malformed result to a classic client with nothing logged.
                if not isinstance(result, dict):
                    raise TypeError(
                        f"The rpc_ handler for {method} must return a dict, "
                        f"not {type(result).__name__}"
                    )
                if not isinstance(result.get("_meta", {}), dict):
                    raise TypeError(
                        f"The rpc_ handler for {method} returned a '_meta' that is "
                        f"{type(result['_meta']).__name__}, not a dict"
                    )
                if stamp:
                    result = self.stamp_result(method=method, result=result)
                return _success_response(msg_id, result)
            except _ProtocolError as e:
                # The caller's problem, not ours — a missing client capability,
                # or `MCPInvalidParams` from the handler. Returned rather than
                # re-raised: letting it leave the `with` block would have the
                # OTel SDK auto-record it as a server failure.
                return e.as_response(msg_id)
            except Exception as e:
                # Real handler failure. It's swallowed into a JSON-RPC error
                # with HTTP 200, so without the span the failure is invisible
                # to OTel-based exception tooling.
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute(ERROR_TYPE, format_exception_type(e))
                log_exception(self.request, e)
                return _error_response(msg_id, INTERNAL_ERROR, "Internal error")

    def stamp_result(self, *, method: str, result: dict[str, Any]) -> dict[str, Any]:
        """Add the fields the spec requires on every result.

        `resultType` marks the result complete, `_meta` names this server, and
        list/read results carry the freshness hints clients cache by. A
        handler that sets any of them keeps its own value. The result's shape
        was already checked in `handle_message` — that guard runs whether or
        not stamping does.
        """
        meta = result.get("_meta", {})
        stamped = dict(result)
        stamped.setdefault("resultType", "complete")

        meta = dict(meta)
        meta.setdefault(
            META_SERVER_INFO,
            {"name": self.name, "version": self.version or settings.VERSION},
        )
        stamped["_meta"] = meta

        if method in self.cacheable_result_methods:
            # Tool and resource listings are filtered per authenticated user
            # by `allowed_for`, so "don't reuse this, and not across users" is
            # the only safe default. Handlers with a stable, public surface
            # can return their own ttlMs/cacheScope.
            stamped.setdefault("ttlMs", 0)
            stamped.setdefault("cacheScope", "private")
        return stamped

    def get_capabilities(self) -> dict[str, Any]:
        """Return the capabilities dict advertised by `server/discover`.

        Override to advertise additional capabilities beyond `tools` /
        `resources`. Call `super().get_capabilities()` to keep the
        defaults.
        """
        capabilities: dict[str, Any] = {}
        if self.get_tools():
            capabilities["tools"] = {}
        if self.get_resources():
            capabilities["resources"] = {}
        return capabilities

    def rpc_server_discover(self, params: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "supportedVersions": [PROTOCOL_VERSION],
            "capabilities": self.get_capabilities(),
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def rpc_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        tools = []
        for tool_cls in self.get_tools():
            tool: dict[str, Any] = {
                "name": tool_cls.name,
                "description": tool_cls.description,
                "inputSchema": tool_cls.input_schema,
            }
            # `annotations` is optional in the spec — omit it when unset (None)
            # so a tool that sets no hints doesn't carry an empty object.
            annotations = tool_cls.annotations
            if annotations:
                tool["annotations"] = annotations
            tools.append(tool)
        return {"tools": tools}

    def rpc_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not tool_name:
            raise MCPInvalidParams("Missing tool name")

        # Unauthorized tools are filtered out by `get_tools()`, so they
        # hit this same "unknown" path — existence isn't leaked.
        tool_cls = next((t for t in self.get_tools() if t.name == tool_name), None)
        if tool_cls is None:
            return _tool_error(f"Unknown tool: {tool_name}")

        # A tool that needs something back from the client (sampling,
        # elicitation) can't run for a client that doesn't offer it. That's a
        # protocol mismatch, not a tool failure, so it goes back as a JSON-RPC
        # error naming what's missing rather than as an `isError` result.
        missing = {
            capability: requirement
            for capability, requirement in tool_cls.required_client_capabilities.items()
            if capability not in self.client_capabilities
        }
        if missing:
            raise _ProtocolError(
                MISSING_REQUIRED_CLIENT_CAPABILITY,
                f"Tool {tool_cls.name} requires client capabilities the client "
                f"did not declare in this request: {', '.join(sorted(missing))}",
                data={"requiredCapabilities": missing},
            )

        # Validate against the advertised input schema before instantiating, so a
        # bad-typed argument returns a clear, model-fixable tool error instead of
        # failing inside `run()` and being logged as a server exception (SEP-1303).
        arguments = params.get("arguments", {})
        if validation_errors := validate_arguments(
            tool_cls.input_schema or {}, arguments
        ):
            return _tool_error("Invalid arguments: " + "; ".join(validation_errors))

        try:
            tool = tool_cls(**arguments)
        except TypeError as e:
            return _tool_error(f"Invalid arguments: {e}")
        tool.mcp = self

        try:
            result = tool.run()
        except MCPToolError as e:
            # Expected, caller-facing failure — surface the message via the
            # in-result error channel and don't log it as a server exception.
            return _tool_error(str(e))
        except Exception as e:
            # Unexpected bug — log for the operator, stay opaque to the caller.
            log_exception(self.request, e)
            return _tool_error("Tool execution failed")

        return {"content": _to_content_blocks(result)}

    def rpc_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        # Only static-URI resources go here; templated ones live under
        # resources/templates/list per the MCP spec.
        return {
            "resources": [
                {
                    "uri": resource_cls.uri,
                    "name": resource_cls.name,
                    "description": resource_cls.description,
                    "mimeType": resource_cls.mime_type,
                }
                for resource_cls in self.get_resources()
                if resource_cls.uri
            ]
        }

    def rpc_resources_templates_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "resourceTemplates": [
                {
                    "uriTemplate": resource_cls.uri_template,
                    "name": resource_cls.name,
                    "description": resource_cls.description,
                    "mimeType": resource_cls.mime_type,
                }
                for resource_cls in self.get_resources()
                if resource_cls.uri_template
            ]
        }

    def rpc_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not uri:
            raise MCPInvalidParams("Missing uri")

        # Unauthorized resources are filtered out by `get_resources()`, so
        # they hit this same "unknown" path — existence isn't leaked.
        resource_cls: type[MCPResource] | None = None
        matched_params: dict[str, Any] = {}
        for candidate in self.get_resources():
            try:
                match = candidate.matches(uri)
            except (TypeError, ValueError) as e:
                # Regex matched but coercion failed — URI looks like this
                # resource's template but the params don't parse.
                raise MCPInvalidParams(f"Invalid URI params: {e}") from e
            if match is not None:
                resource_cls = candidate
                matched_params = match
                break

        if resource_cls is None:
            # `data.uri` echoes what wasn't found, so a client doesn't have to
            # parse it back out of the message (SEP-2164).
            raise MCPInvalidParams(f"Unknown resource: {uri}", data={"uri": uri})

        try:
            resource = resource_cls(**matched_params)
        except TypeError as e:
            raise MCPInvalidParams(f"Invalid URI params: {e}") from e
        resource.mcp = self

        # Resources have no in-band error channel like tools' `isError`, so
        # read() exceptions propagate and surface as INTERNAL_ERROR.
        content = resource.read()

        entry: dict[str, Any] = {"uri": uri, "mimeType": resource.mime_type}
        if isinstance(content, bytes):
            entry["blob"] = _b64(content)
        else:
            entry["text"] = content
        return {"contents": [entry]}


_CONTENT_BLOCK_TYPES = {"text", "image", "audio", "resource", "resource_link"}


def _decode_request(raw: bytes | str) -> dict[str, Any]:
    """Decode the body and confirm it's a JSON-RPC 2.0 message at all.

    Split from the checks below because these are the failures with no `id` to
    correlate against — the body didn't parse, or what it parsed to isn't a
    request. JSON-RPC says the reply's `id` is null exactly then.
    """
    try:
        message = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise _ProtocolError(PARSE_ERROR, f"Parse error: {e}") from e

    if not isinstance(message, dict):
        raise _ProtocolError(INVALID_REQUEST, "Request must be a JSON object")

    if message.get("jsonrpc") != "2.0":
        raise _ProtocolError(
            INVALID_REQUEST,
            "Missing or invalid 'jsonrpc' version; must be '2.0'",
        )

    return message


def _read_method(message: dict[str, Any]) -> str:
    """Return the message's `method`, which every message must name."""
    method = message.get("method")
    if not method or not isinstance(method, str):
        raise _ProtocolError(INVALID_REQUEST, "Missing or invalid method")
    return method


def _read_params(message: dict[str, Any]) -> dict[str, Any]:
    """Return the message's `params` as a dict, absent or explicit null as `{}`.

    Checked only after the caller knows this is a request and not a
    notification: by-position params (an array) are legal JSON-RPC that MCP
    methods don't take, and rejecting them is still a reply — which a
    notification may never receive.
    """
    params = message.get("params")
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise _ProtocolError(INVALID_PARAMS, "'params' must be an object")
    return params


def _decode_header_value(value: str) -> str:
    """Decode the `=?base64?...?=` sentinel a client uses for non-ASCII values.

    The markers are case-sensitive, and a value the client didn't wrap comes
    back untouched.
    """
    if not (value.startswith("=?base64?") and value.endswith("?=")):
        return value
    encoded = value.removeprefix("=?base64?").removesuffix("?=")
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return value


def _tool_error(text: str) -> dict[str, Any]:
    """A `tools/call` result carrying a caller-facing failure via `isError`."""
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _to_content_blocks(value: Any) -> list[dict[str, Any]]:
    """Convert a tool's `run()` return value into MCP content blocks.

    Recognized shapes (in order):
    - `str` → one text block
    - a dict with `type` in the known content types → that single block
    - a list where every item is such a dict → those blocks, in order
    - any other `dict`/`list` → one text block with the value JSON-serialized
    - anything else → one text block with `str(value)`

    `bytes` values in `data` (image/audio) or `resource.blob` (embedded
    resource) are base64-encoded automatically.
    """
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, dict) and _is_content_block(value):
        return [_encode_binary(value)]
    if isinstance(value, list) and value and all(_is_content_block(v) for v in value):
        return [_encode_binary(v) for v in value]
    if isinstance(value, dict | list):
        return [{"type": "text", "text": json.dumps(value, default=str)}]
    return [{"type": "text", "text": str(value)}]


def _is_content_block(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") in _CONTENT_BLOCK_TYPES


def _encode_binary(block: dict[str, Any]) -> dict[str, Any]:
    """Encode `bytes` fields to base64 in-place on a content block copy."""
    block_type = block.get("type")
    if block_type in ("image", "audio"):
        data = block.get("data")
        if isinstance(data, bytes):
            return {**block, "data": _b64(data)}
    elif block_type == "resource":
        resource = block.get("resource")
        if isinstance(resource, dict):
            blob = resource.get("blob")
            if isinstance(blob, bytes):
                return {
                    **block,
                    "resource": {**resource, "blob": _b64(blob)},
                }
    return block


def _success_response(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}
