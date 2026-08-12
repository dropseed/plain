# plain-mcp changelog

## [0.7.0](https://github.com/dropseed/plain/releases/plain-mcp@0.7.0) (2026-08-12)

### What's changed

- `MCPView.tools` and `resources` are now tuple-typed (`tuple[type[MCPTool], ...]`); list declarations still work at runtime but fail type checking ([f52e18f532](https://github.com/dropseed/plain/commit/f52e18f532))
- `register_tool()`/`register_resource()` rebuild the class attribute as a tuple instead of mutating a list in place — this also makes registration work correctly on subclasses that declare their own `tools` tuple ([f52e18f532](https://github.com/dropseed/plain/commit/f52e18f532))
- `MCPTool.input_schema` and `annotations` are annotated `ClassVar`, matching how they're declared per tool class ([f52e18f532](https://github.com/dropseed/plain/commit/f52e18f532))
- OAuth protected-resource metadata attributes (`authorization_servers`, `oauth_scopes_supported`) are tuples ([f52e18f532](https://github.com/dropseed/plain/commit/f52e18f532))

### Upgrade instructions

- Convert `tools = [...]` / `resources = [...]` declarations to tuples: `tools = (Echo, Search)` — single-element declarations need the trailing comma: `tools = (Echo,)`

## [0.6.0](https://github.com/dropseed/plain/releases/plain-mcp@0.6.0) (2026-08-10)

### What's changed

- **Which revision a request belongs to is now decided by its envelope alone.** A request is modern if it restates the protocol version in `params._meta`, or if its `MCP-Protocol-Version` header names `2026-07-28` exactly; everything else is classic. Previously the presence of an `Mcp-Method` header (or a version header naming anything outside `CLASSIC_PROTOCOL_VERSIONS`) also selected the modern path — which misrouted a fully conformant classic client that happened to send `Mcp-Method` too, rejecting it mid-session with a `-32602` for a `params._meta` envelope its revision never defined. claude.ai's connector proxy sends exactly that shape. Unrecognized headers are spec-legal for any client, SDK, or middlebox, so their presence is no longer treated as evidence of a revision. ([2ad52d8b26](https://github.com/dropseed/plain/commit/2ad52d8b26))
- **Routing facts are stamped on the request span as they're learned** — `mcp.method`, `mcp.revision` (`classic` / `modern`), `mcp.protocol_version_header`, `mcp.method_header_present`, and `mcp.meta_protocol_version_present`. A request that dies partway up the validation ladder carries whatever was known by then, which is what a "why was this client rejected?" investigation reads first. ([2ad52d8b26](https://github.com/dropseed/plain/commit/2ad52d8b26))
- **Every JSON-RPC error reply is now visible server-side before it ships.** The code and message land on the request span as `mcp.error.code` / `mcp.error.message`, and everything except an internal error (`-32603`, already logged with a traceback) logs a `MCP request rejected` warning on the `plain.mcp` logger carrying the routing facts. Classic replies ride HTTP 200, so this is otherwise the only server-side trace of a rejected classic request — and a client that swallows the response body surfaces nothing better than "connection failed". ([2ad52d8b26](https://github.com/dropseed/plain/commit/2ad52d8b26))

### Upgrade instructions

- No changes required.
- This supersedes the 0.5.0 note that classic requests send none of the `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name` headers. Any of them may appear on any request, from any revision — infrastructure keying on them should treat them as advisory and fall back to inspecting the body.
- A modern client that relied on `Mcp-Method` alone to be routed onto the modern ladder must now declare `io.modelcontextprotocol/protocolVersion` in `params._meta`, or send `MCP-Protocol-Version: 2026-07-28`. Without either, it's served as a classic client.
- Expect new `WARNING`-level `MCP request rejected` records on the `plain.mcp` logger — one per rejected request. Adjust that logger's level if you don't want them.

## [0.5.0](https://github.com/dropseed/plain/releases/plain-mcp@0.5.0) (2026-08-07)

### What's changed

- **Classic MCP revisions (`2025-03-26`, `2025-06-18`, `2025-11-25`) are served again**, through a compatibility branch for clients that still open with `initialize` — claude.ai's connector proxy among them. A request that declares `2026-07-28` in neither the `MCP-Protocol-Version` header nor `params._meta` is routed to the new `handle_classic_message`, which answers `initialize` and `ping` directly and sends every other method to the same `rpc_` handlers. New `CLASSIC_PROTOCOL_VERSIONS` constant; `handle_classic_message`, `classic_initialize_result`, and `classic_ping_result` are all overridable. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- The classic branch stays stateless — no `Mcp-Session-Id` is issued (the client proceeds sessionless) and the GET stream is still declined with a `405`, both allowances the classic spec grants. Nothing from `initialize` is remembered, so tools with `required_client_capabilities` refuse classic clients, and JSON-RPC batch arrays (transport-level in `2025-03-26` only) are rejected with `-32600`. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- Every classic reply, errors included, travels at HTTP 200 — the statuses in `ERROR_CODE_HTTP_STATUS` are `2026-07-28` vocabulary, and a classic client reads the JSON-RPC error from the body (a 404 on `initialize` is what sends one chasing the deprecated SSE transport). A classic unknown-method error also drops the "This server speaks MCP 2026-07-28" claim, which a client that just negotiated a classic version would read as a version mismatch. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- Classic dispatch goes through `handle_message` like any modern request, so `initialize`/`ping` get the same `rpc <method>` SERVER span and the same `-32603`-in-the-body handler-failure funnel. Results aren't stamped on that path — `resultType`, `serverInfo`, and the `ttlMs`/`cacheScope` freshness hints are vocabulary a classic client never asked for. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- **`rpc_` handler result-shape validation moved from `stamp_result` into `handle_message`**, so the clear `TypeError` for a non-dict result (or a non-dict `_meta`) is raised on both revision paths. Without the move, an unstamped classic reply would have shipped a malformed result with nothing logged. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- The `-32021` missing-capability message now reads "did not declare in this request", since capabilities are restated per-request on the modern path and unavailable on the classic one. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))
- README: the spec-coverage table's "Legacy protocol versions — not supported" row is now "Classic protocol versions (`2025-03-26` … `2025-11-25`) — built in", and the header guarantee, validation ladder, and protocol-version FAQ all document the branch and its limits. A new CSRF note warns against adding your MCP path to `CSRF_EXEMPT_PATHS` — for a session-authenticated MCP view, that check is what blocks cross-site tool invocation from a browser, and classic requests carry no custom headers that would force a CORS preflight. ([7a57d06229](https://github.com/dropseed/plain/commit/7a57d06229))

### Upgrade instructions

- No changes required — existing `rpc_` methods, tools, and resources serve both revision families unchanged.
- If infrastructure in front of your app routes or authorizes on `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name`, treat their absence as "inspect the body" rather than "allow" — classic requests send none of them.
- Tools declaring `required_client_capabilities` will refuse classic clients, since capabilities announced at `initialize` aren't retained. Nothing to change, but expect a `-32021` from older clients.
- If you added your MCP path to `CSRF_EXEMPT_PATHS`, remove it — a session-authenticated MCP view needs that check, and non-browser clients skip it automatically.

## [0.4.0](https://github.com/dropseed/plain/releases/plain-mcp@0.4.0) (2026-08-02)

### What's changed

- **The server now speaks MCP `2026-07-28`, the stateless revision — and only that version.** There is no `initialize` handshake, no sessions, and no server-to-client stream; every POST is one self-describing JSON-RPC request. `rpc_initialize` and `rpc_ping` are gone — a client that opens with `initialize` (or any pre-`2026-07-28` method) gets a `-32601` at HTTP 404 naming the version this server speaks. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- Each request restates the client's identity in `params._meta` — `io.modelcontextprotocol/protocolVersion` and `clientCapabilities` are required, `clientInfo` optional — and mirrors the routing-relevant parts into headers (`MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` on target-naming methods), which the server validates against the body. Failures answer with the new spec error codes: `-32602` for missing `_meta`, `-32020` for a header mismatch, `-32022` for an unsupported protocol version. What the client sent is available as `self.client_info` / `self.client_capabilities`. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- JSON-RPC errors now ride spec-mandated HTTP statuses via one `ERROR_CODE_HTTP_STATUS` table — unknown method is 404, protocol/validation errors are 400, and an internal error (`-32603`) stays at 200. The private `-32001`/`-32003`/`-32004` auth codes are gone: for framework exceptions the HTTP status leads and the JSON-RPC code follows from it (401 with `WWW-Authenticate` is the real auth signal). ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- **New `server/discover` built-in** replaces `initialize` for discovery — it reports `supportedVersions`, capabilities, and the new `MCPView.instructions` attribute (free-form guidance for the model driving the server). Capability values are now bare `{}` (no more `listChanged`/`subscribe` flags). ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- **Results are stamped automatically**, including from your own `rpc_` methods: `resultType: "complete"`, `_meta` with `io.modelcontextprotocol/serverInfo`, and `ttlMs: 0` / `cacheScope: "private"` on list and read results. Handler-set values win. Two extensible class attributes control the stamping and header checks for custom methods: `cacheable_result_methods` and `name_header_params`. An `rpc_` handler must now return a dict — anything else raises a clear `TypeError` instead of an opaque internal error. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- **New `MCPTool.required_client_capabilities`** — a tool that calls back to the client (sampling, elicitation) declares what it needs, and a client that didn't announce it gets a `-32021` naming exactly what's missing instead of a confusing tool failure. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- `MCPInvalidParams` now accepts a structured `data=` payload (e.g. `raise MCPInvalidParams(f"Unknown resource: {uri}", data={"uri": uri})`), and unknown-resource errors echo the URI in `data.uri`. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))
- The README documents the full request/validation flow and adds a spec-coverage table, backed by a machine-checked conformance baseline that fails the build if reality drifts from the table. ([4c36e05626](https://github.com/dropseed/plain/commit/4c36e05626))

### Upgrade instructions

- Clients must speak MCP `2026-07-28` — recent MCP client libraries handle the new `_meta`/header envelope for you. Older clients that open with `initialize` can no longer connect.
- If you overrode `rpc_initialize` or `rpc_ping`, remove those overrides — discovery customization now goes through `rpc_server_discover`, `get_capabilities()`, and the `instructions` attribute.
- If you referenced the removed error constants (`UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`), switch to reading the HTTP status instead — non-400/500 statuses now use the status itself as the JSON-RPC code.
- Custom `rpc_` methods must return a dict; their results are now stamped with `resultType`/`serverInfo` automatically, and list-shaped methods should be added to `cacheable_result_methods` (and target-naming ones to `name_header_params`).

## [0.3.1](https://github.com/dropseed/plain/releases/plain-mcp@0.3.1) (2026-07-21)

### What's changed

- Documented that apps with `URLS_TRAILING_SLASH = True` should mount the OAuth protected-resource metadata paths with `force_trailing_slash=False`, since MCP clients won't reliably follow a 308 trailing-slash redirect to the `.well-known` URL. ([53e2970723](https://github.com/dropseed/plain/commit/53e2970723))

### Upgrade instructions

- If your app sets `URLS_TRAILING_SLASH = True` and serves OAuth-protected MCP endpoints, mount the `.well-known/oauth-protected-resource` paths with `force_trailing_slash=False` as shown in the README.

## [0.3.0](https://github.com/dropseed/plain/releases/plain-mcp@0.3.0) (2026-07-10)

### What's changed

- `tools/call` arguments are now validated against the tool's advertised input schema before the tool is instantiated. A missing or wrong-typed argument comes back as a clear, model-fixable `isError` message (e.g. `Invalid arguments: 'limit' must be an integer`) instead of blowing up inside `run()` and being logged as a server exception. Validation covers the schema shapes derived from type hints — primitives, `Literal[...]` enums, `list[T]`, `T | None` — and follows JSON Schema semantics (booleans are not integers; `5.0` is a valid integer). If you hand-write an `input_schema` with richer JSON Schema keywords (`oneOf`, `$ref`, `pattern`, numeric bounds), those pass through unvalidated — check them in `__init__` or `run()` yourself. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))
- Parameters with no annotation, `Any`, or an unrecognized type now advertise a permissive empty schema (accepts any JSON value) instead of `{"type": "string"}`, so clients are no longer steered into sending strings for values that aren't. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))
- `*args` / `**kwargs` parameters on a tool's `__init__` are no longer advertised as schema properties — previously a `**kwargs` tool advertised a required `kwargs` property that no client could ever satisfy. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))

### Upgrade instructions

- No changes required for tools whose type hints match what clients actually send. If a tool was knowingly accepting schema-mismatched arguments (e.g. a param annotated `int` that clients send as a string), those calls are now rejected before `__init__` — loosen the annotation (or hand-write `input_schema`) to keep accepting them.

## [0.2.1](https://github.com/dropseed/plain/releases/plain-mcp@0.2.1) (2026-06-30)

### What's changed

- Documentation only: the MCP endpoint examples now use a slashless path (`/mcp` rather than `/mcp/`) consistently across the README and the `MCPView` docstring. No code or behavior changes. ([0399d8b](https://github.com/dropseed/plain/commit/0399d8b1ad))

### Upgrade instructions

- No changes required.

## [0.2.0](https://github.com/dropseed/plain/releases/plain-mcp@0.2.0) (2026-06-28)

### What's changed

- New `MCPToolError` exception, exported from `plain.mcp`. Raise it from a tool's `run()` to signal an expected, caller-facing failure (bad input, not found, forbidden): the message is returned to the client with `isError: true` — MCP's in-result error channel, so the model can self-correct — and it is _not_ logged as a server exception. Any other exception is still treated as a bug: logged server-side and returned as an opaque "Tool execution failed" ([4989aeb](https://github.com/dropseed/plain/commit/4989aeb488)).
- New optional `annotations` attribute on `MCPTool`. Set it to a raw MCP-wire-format dict (e.g. `{"readOnlyHint": True}`) to advertise [tool annotation hints](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-annotations); clients like Claude group read-only tools and gate approval on the rest. The dict is emitted verbatim — any current or future spec hint works without a `plain.mcp` change — and a tool that sets no annotations carries no `annotations` object at all. Inherited like any class attribute, so a shared base tool can set it once ([88588a0](https://github.com/dropseed/plain/commit/88588a0108)).
- Documented the typed `self.mcp` pattern: re-annotate `mcp` on a per-app base tool or resource (`mcp: AppMCP`) for typed access to your view's `user`, `scopes`, and other subclass attributes. The full MCP↔OAuth client handshake walkthrough now lives in this README as well ([3460d76](https://github.com/dropseed/plain/commit/3460d76137)).

### Upgrade instructions

- No changes required. Optionally raise `MCPToolError` for expected tool failures, and set `annotations = {"readOnlyHint": True}` on read-only tools so clients can group and auto-allow them.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-mcp@0.1.0) (2026-06-26)

Initial release of `plain.mcp` — build a Model Context Protocol (MCP) server inside a Plain app.

### What's changed

- `MCPView`: an MCP server endpoint that exposes `tools` and `resources` over the Streamable HTTP transport (JSON-RPC), with declarative or imperative tool/resource registration.
- Composable authentication — session auth via `AuthView`, a bearer-token check in `before_request`, or OAuth.
- Issuer-agnostic OAuth resource-server support: the `OAuthResourceServer` mixin + `TokenInfo` seam, an RFC 9728 protected-resource metadata view (`MCPProtectedResourceView`), and a `WWW-Authenticate` challenge, so an endpoint can accept bearer tokens from any issuer (pair with `plain.oauthserver`).
- Implements MCP protocol version 2025-11-25, with version negotiation in `initialize` and `MCP-Protocol-Version` header validation.

### Upgrade instructions

- No changes required (first release).
