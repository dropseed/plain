from __future__ import annotations

import enum
import json
from typing import Any, Literal

from plain.mcp import MCPResource, MCPTool, MCPToolError, MCPView
from plain.test import RequestFactory, patch, raises


class _Mode(enum.StrEnum):
    # Module-level so `get_type_hints` can resolve it under
    # `from __future__ import annotations` (a local class inside a test would
    # fail to resolve and silently fall back to a permissive schema).
    FAST = "fast"
    SLOW = "slow"


def _make_request(
    method: str, params: dict[str, Any] | None = None, msg_id: int = 1
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
    )


def _instantiate(cls: type[MCPView]) -> MCPView:
    """Build an MCPView instance with a stub request for unit tests."""
    request = RequestFactory().post("/mcp", body=b"", content_type="application/json")
    return cls(request=request)


def _call(mcp: MCPView, *args: Any, **kwargs: Any) -> dict[str, Any]:
    response = mcp.handle_message(*args, **kwargs)
    assert response is not None
    return response


class TestMCPProtocol:
    def _mcp(self) -> MCPView:
        class _TestMCP(MCPView):
            name = "test"

        return _instantiate(_TestMCP)

    def test_initialize(self) -> None:
        response = _call(self._mcp(), _make_request("initialize"))
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "protocolVersion" in response["result"]
        assert response["result"]["serverInfo"]["name"] == "test"

    def test_ping(self) -> None:
        response = _call(self._mcp(), _make_request("ping"))
        assert response["result"] == {}

    def test_unknown_method(self) -> None:
        response = _call(self._mcp(), _make_request("bogus/method"))
        assert response["error"]["code"] == -32601

    def test_underscore_method_name_rejected(self) -> None:
        """`tools_list` must not collide with the `tools/list` → `rpc_tools_list` dispatch.

        JSON-RPC method names in MCP use `/` as the separator, so an
        underscore in a raw method name is never valid — rejecting it
        keeps the `/` → `_` rewrite collision-free.
        """
        response = _call(self._mcp(), _make_request("tools_list"))
        assert response["error"]["code"] == -32601

    def test_parse_error(self) -> None:
        response = _call(self._mcp(), b"not json")
        assert response["error"]["code"] == -32700

    def test_missing_jsonrpc_version_rejected(self) -> None:
        msg = json.dumps({"id": 1, "method": "ping", "params": {}})
        response = _call(self._mcp(), msg)
        assert response["error"]["code"] == -32600
        assert response["id"] == 1

    def test_wrong_jsonrpc_version_rejected(self) -> None:
        msg = json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping", "params": {}})
        response = _call(self._mcp(), msg)
        assert response["error"]["code"] == -32600

    def test_array_params_rejected(self) -> None:
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []})
        response = _call(self._mcp(), msg)
        assert response["error"]["code"] == -32602

    def test_null_params_treated_as_empty(self) -> None:
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None})
        response = _call(self._mcp(), msg)
        assert response["result"] == {}

    def test_notification_returns_none(self) -> None:
        msg = json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        assert self._mcp().handle_message(msg) is None

    def test_tools_list_empty(self) -> None:
        response = _call(self._mcp(), _make_request("tools/list"))
        assert response["result"]["tools"] == []


class TestToolRegistration:
    def test_tools_list_attr_with_class(self) -> None:
        class Greet(MCPTool):
            """Say hello."""

            def __init__(self, name: str):
                self.name = name

            def run(self) -> str:
                return f"Hello, {self.name}!"

        class MyMCP(MCPView):
            name = "test"
            tools = [Greet]

        mcp = _instantiate(MyMCP)
        response = _call(mcp, _make_request("tools/list"))
        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "Greet"
        assert tools[0]["description"] == "Say hello."
        assert tools[0]["inputSchema"]["properties"]["name"]["type"] == "string"
        assert "name" in tools[0]["inputSchema"]["required"]

    def test_tool_emits_annotations(self) -> None:
        class ListThings(MCPTool):
            """List things."""

            annotations = {"readOnlyHint": True}

            def run(self) -> str:
                return "ok"

        class MyMCP(MCPView):
            name = "test"
            tools = [ListThings]

        tools = _call(_instantiate(MyMCP), _make_request("tools/list"))["result"][
            "tools"
        ]
        assert tools[0]["annotations"] == {"readOnlyHint": True}

    def test_tool_without_annotations_omits_key(self) -> None:
        class DoThing(MCPTool):
            """Do a thing."""

            def run(self) -> str:
                return "ok"

        class MyMCP(MCPView):
            name = "test"
            tools = [DoThing]

        tools = _call(_instantiate(MyMCP), _make_request("tools/list"))["result"][
            "tools"
        ]
        assert "annotations" not in tools[0]

    def test_tool_annotations_pass_through_unknown_keys(self) -> None:
        # Annotations are emitted verbatim, so a hint plain-mcp doesn't model
        # (a newer spec field) works without a framework change.
        class Future(MCPTool):
            """A tool using a not-yet-modeled hint."""

            annotations = {"readOnlyHint": True, "sensitiveHint": True}

            def run(self) -> str:
                return "ok"

        class MyMCP(MCPView):
            name = "test"
            tools = [Future]

        tools = _call(_instantiate(MyMCP), _make_request("tools/list"))["result"][
            "tools"
        ]
        assert tools[0]["annotations"] == {
            "readOnlyHint": True,
            "sensitiveHint": True,
        }

    def test_tool_annotations_inherited(self) -> None:
        # A base tool's annotations are inherited by subclasses via normal
        # class-attribute inheritance — no special handling.
        class ReadTool(MCPTool):
            annotations = {"readOnlyHint": True}

        class ListThings(ReadTool):
            """List things."""

            def run(self) -> str:
                return "ok"

        class MyMCP(MCPView):
            name = "test"
            tools = [ListThings]

        tools = _call(_instantiate(MyMCP), _make_request("tools/list"))["result"][
            "tools"
        ]
        assert tools[0]["annotations"] == {"readOnlyHint": True}

    def test_register_classmethod(self) -> None:
        class MyMCP(MCPView):
            name = "test"

        class ExtTool(MCPTool):
            """External tool."""

            def __init__(self, x: str):
                self.x = x

            def run(self) -> str:
                return self.x

        MyMCP.register_tool(ExtTool)

        mcp = _instantiate(MyMCP)
        response = _call(mcp, _make_request("tools/list"))
        names = [t["name"] for t in response["result"]["tools"]]
        assert names == ["ExtTool"]

    def test_register_does_not_bleed_across_siblings(self) -> None:
        class AdminMCP(MCPView):
            name = "admin"

        class AppMCP(MCPView):
            name = "app"

        class ToolA(MCPTool):
            def run(self) -> str:
                return "a"

        AdminMCP.register_tool(ToolA)

        admin = _instantiate(AdminMCP)
        app = _instantiate(AppMCP)

        assert len(_call(admin, _make_request("tools/list"))["result"]["tools"]) == 1
        assert len(_call(app, _make_request("tools/list"))["result"]["tools"]) == 0


class TestToolExecution:
    def test_tools_call(self) -> None:
        class Add(MCPTool):
            def __init__(self, a: int, b: int):
                self.a = a
                self.b = b

            def run(self) -> str:
                return str(self.a + self.b)

        class MyMCP(MCPView):
            name = "test"
            tools = [Add]

        mcp = _instantiate(MyMCP)
        response = _call(
            mcp,
            _make_request("tools/call", {"name": "Add", "arguments": {"a": 2, "b": 3}}),
        )
        assert response["result"]["content"][0]["text"] == "5"

    def test_tools_call_unknown(self) -> None:
        class MyMCP(MCPView):
            name = "test"

        mcp = _instantiate(MyMCP)
        response = _call(
            mcp,
            _make_request("tools/call", {"name": "nonexistent", "arguments": {}}),
        )
        assert response["result"]["isError"] is True
        assert "nonexistent" in response["result"]["content"][0]["text"]

    def test_tools_call_bad_arguments(self) -> None:
        class Add(MCPTool):
            def __init__(self, a: int, b: int):
                self.a = a
                self.b = b

            def run(self) -> str:
                return str(self.a + self.b)

        class MyMCP(MCPView):
            name = "test"
            tools = [Add]

        mcp = _instantiate(MyMCP)
        response = _call(
            mcp,
            _make_request(
                "tools/call",
                {"name": "Add", "arguments": {"a": 1, "wrong_param": 2}},
            ),
        )
        assert response["result"]["isError"] is True
        assert "Invalid arguments" in response["result"]["content"][0]["text"]

    def test_tools_call_error_returns_iserror(self) -> None:
        class BadTool(MCPTool):
            def run(self) -> str:
                raise RuntimeError("something broke")

        class MyMCP(MCPView):
            name = "test"
            tools = [BadTool]

        mcp = _instantiate(MyMCP)
        response = _call(
            mcp,
            _make_request("tools/call", {"name": "BadTool", "arguments": {}}),
        )
        assert response["result"]["isError"] is True
        assert response["result"]["content"][0]["text"] == "Tool execution failed"

    def test_tool_error_surfaces_message_without_logging(self) -> None:
        class PickyTool(MCPTool):
            def run(self) -> str:
                raise MCPToolError("No widget named 'foo'")

        class MyMCP(MCPView):
            name = "test"
            tools = [PickyTool]

        import plain.mcp.views as mcp_views

        logged: list[Any] = []
        with patch(mcp_views, "log_exception", lambda *a, **k: logged.append(a)):
            mcp = _instantiate(MyMCP)
            response = _call(
                mcp,
                _make_request("tools/call", {"name": "PickyTool", "arguments": {}}),
            )
        # Expected failure: the caller sees the message via isError, and it is
        # NOT logged as a server exception (unlike an unexpected error).
        assert response["result"]["isError"] is True
        assert response["result"]["content"][0]["text"] == "No widget named 'foo'"
        assert logged == []

    def test_tool_receives_mcp_reference(self) -> None:
        class Reflect(MCPTool):
            def run(self) -> str:
                return type(self.mcp).__name__ if self.mcp else "none"

        class MyMCP(MCPView):
            name = "test"
            tools = [Reflect]

        mcp = _instantiate(MyMCP)
        response = _call(
            mcp,
            _make_request("tools/call", {"name": "Reflect", "arguments": {}}),
        )
        assert response["result"]["content"][0]["text"] == "MyMCP"


class TestArgumentValidation:
    """Arguments are validated against the advertised input schema before the
    tool runs, so bad input becomes a clear tool error (SEP-1303) rather than
    an opaque failure inside `run()`."""

    def _add_mcp(self) -> type[MCPView]:
        class Add(MCPTool):
            def __init__(self, a: int, b: int):
                self.a = a
                self.b = b

            def run(self) -> str:
                return str(self.a + self.b)

        class MyMCP(MCPView):
            name = "test"
            tools = [Add]

        return MyMCP

    def _greet_mcp(self) -> type[MCPView]:
        # Param is `who`, not `name`, to avoid shadowing MCPTool's own `name`
        # attribute (which is typed `str`, so an optional `str | None` collides).
        class Greet(MCPTool):
            def __init__(self, who: str | None = None):
                self.who = who

            def run(self) -> str:
                return f"Hello, {self.who}"

        class MyMCP(MCPView):
            name = "test"
            tools = [Greet]

        return MyMCP

    def test_wrong_type_rejected_before_run(self) -> None:
        # A string where an integer is declared must be rejected up front —
        # NOT run through `a + b` and logged as a server exception.
        import plain.mcp.views as mcp_views

        logged: list[Any] = []
        with patch(mcp_views, "log_exception", lambda *a, **k: logged.append(a)):
            response = _call(
                _instantiate(self._add_mcp()),
                _make_request(
                    "tools/call", {"name": "Add", "arguments": {"a": "x", "b": 3}}
                ),
            )
        assert response["result"]["isError"] is True
        assert "'a' must be an integer" in response["result"]["content"][0]["text"]
        # The whole point: this input error is not logged as a server exception.
        assert logged == []

    def test_bool_is_not_an_integer(self) -> None:
        # JSON `true` is a boolean, not an integer — reject it.
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request(
                "tools/call", {"name": "Add", "arguments": {"a": True, "b": 3}}
            ),
        )
        assert response["result"]["isError"] is True
        assert "'a' must be an integer" in response["result"]["content"][0]["text"]

    def test_missing_required_argument(self) -> None:
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request("tools/call", {"name": "Add", "arguments": {"a": 1}}),
        )
        assert response["result"]["isError"] is True
        assert (
            "missing required argument: b" in response["result"]["content"][0]["text"]
        )

    def test_enum_violation_lists_allowed_values(self) -> None:
        class SetStatus(MCPTool):
            def __init__(self, status: Literal["pending", "done"]):
                self.status = status

            def run(self) -> str:
                return self.status

        class MyMCP(MCPView):
            name = "test"
            tools = [SetStatus]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "SetStatus", "arguments": {"status": "bogus"}}
            ),
        )
        assert response["result"]["isError"] is True
        text = response["result"]["content"][0]["text"]
        assert "'status' must be one of: pending, done" in text

    def test_optional_accepts_null(self) -> None:
        response = _call(
            _instantiate(self._greet_mcp()),
            _make_request("tools/call", {"name": "Greet", "arguments": {"who": None}}),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "Hello, None"

    def test_optional_rejects_wrong_type_with_null_branch(self) -> None:
        response = _call(
            _instantiate(self._greet_mcp()),
            _make_request("tools/call", {"name": "Greet", "arguments": {"who": 5}}),
        )
        assert response["result"]["isError"] is True
        assert (
            "'who' must be a string or null" in response["result"]["content"][0]["text"]
        )

    def test_list_item_type_validated(self) -> None:
        class Sum(MCPTool):
            def __init__(self, ids: list[int]):
                self.ids = ids

            def run(self) -> str:
                return str(sum(self.ids))

        class MyMCP(MCPView):
            name = "test"
            tools = [Sum]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "Sum", "arguments": {"ids": [1, "two", 3]}}
            ),
        )
        assert response["result"]["isError"] is True
        assert "'ids[1]' must be an integer" in response["result"]["content"][0]["text"]

    def test_object_type_rejects_non_dict(self) -> None:
        class Store(MCPTool):
            def __init__(self, payload: dict):
                self.payload = payload

            def run(self) -> str:
                return str(self.payload)

        class MyMCP(MCPView):
            name = "test"
            tools = [Store]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "Store", "arguments": {"payload": "nope"}}
            ),
        )
        assert response["result"]["isError"] is True
        assert "'payload' must be an object" in response["result"]["content"][0]["text"]

    def test_unannotated_param_accepts_any_type(self) -> None:
        # Unannotated params advertise a permissive schema, so a non-string
        # argument the tool wants must not be rejected by validation.
        class Store(MCPTool):
            def __init__(self, data):  # noqa: ANN001
                self.data = data

            def run(self) -> dict:
                return self.data

        class MyMCP(MCPView):
            name = "test"
            tools = [Store]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "Store", "arguments": {"data": {"k": "v"}}}
            ),
        )
        assert "isError" not in response["result"]

    def test_int_literal_rejects_bool(self) -> None:
        # Python `True == 1`, but JSON `true` is not a valid integer Literal.
        class SetLevel(MCPTool):
            def __init__(self, level: Literal[1, 2, 3]):
                self.level = level

            def run(self) -> str:
                return str(self.level)

        class MyMCP(MCPView):
            name = "test"
            tools = [SetLevel]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "SetLevel", "arguments": {"level": True}}
            ),
        )
        assert response["result"]["isError"] is True
        assert "'level' must be one of" in response["result"]["content"][0]["text"]

    def test_str_enum_literal_accepts_serialized_value(self) -> None:
        # A Literal over StrEnum members serializes to plain strings in the
        # advertised schema; the incoming plain string must still validate
        # (a strict `type() is type()` check would wrongly reject it).
        class SetMode(MCPTool):
            def __init__(self, mode: Literal[_Mode.FAST, _Mode.SLOW]):
                self.mode = mode

            def run(self) -> str:
                return str(self.mode)

        class MyMCP(MCPView):
            name = "test"
            tools = [SetMode]

        # Guard against the silent-permissive fallback: the schema must really
        # carry the enum, otherwise this test proves nothing.
        assert SetMode.input_schema is not None
        assert SetMode.input_schema["properties"]["mode"]["enum"] == ["fast", "slow"]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "SetMode", "arguments": {"mode": "fast"}}
            ),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "fast"

    def test_int_literal_accepts_integral_float(self) -> None:
        # `1.0` equals integer `1` numerically (JSON Schema treats them equal),
        # consistent with a bare `int` param accepting `5.0`.
        class SetLevel(MCPTool):
            def __init__(self, level: Literal[1, 2, 3]):
                self.level = level

            def run(self) -> str:
                return str(self.level)

        class MyMCP(MCPView):
            name = "test"
            tools = [SetLevel]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "SetLevel", "arguments": {"level": 1.0}}
            ),
        )
        assert "isError" not in response["result"]

    def test_malformed_enum_schema_is_permissive(self) -> None:
        # A hand-written schema with a non-list `enum` must degrade permissively,
        # not crash validation into a server error.
        class Custom(MCPTool):
            input_schema = {
                "type": "object",
                "properties": {"x": {"enum": 5}},  # malformed: enum must be a list
            }

            def __init__(self, x: int):
                self.x = x

            def run(self) -> str:
                return str(self.x)

        class MyMCP(MCPView):
            name = "test"
            tools = [Custom]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Custom", "arguments": {"x": 1}}),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "1"

    def test_malformed_enum_with_type_mismatch_reports_clean_error(self) -> None:
        # A non-list enum alongside a `type`: a value failing the type must
        # produce a clean tool error via _describe_type, not crash it into a
        # logged INTERNAL_ERROR.
        class Custom(MCPTool):
            input_schema = {
                "type": "object",
                "properties": {"x": {"type": "integer", "enum": 99}},
            }

            def __init__(self, x: int):
                self.x = x

            def run(self) -> str:
                return str(self.x)

        class MyMCP(MCPView):
            name = "test"
            tools = [Custom]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Custom", "arguments": {"x": "abc"}}),
        )
        assert response["result"]["isError"] is True
        assert "'x' must be an integer" in response["result"]["content"][0]["text"]

    def test_malformed_anyof_schema_is_permissive(self) -> None:
        class Custom(MCPTool):
            input_schema = {
                "type": "object",
                "properties": {"x": {"anyOf": 5}},  # malformed: anyOf must be a list
            }

            def __init__(self, x: int):
                self.x = x

            def run(self) -> str:
                return str(self.x)

        class MyMCP(MCPView):
            name = "test"
            tools = [Custom]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Custom", "arguments": {"x": 1}}),
        )
        assert "isError" not in response["result"]

    def test_non_dict_input_schema_is_permissive(self) -> None:
        class Weird(MCPTool):
            input_schema = "totally not a schema"  # misconfigured, non-dict

            def __init__(self, x: int):
                self.x = x

            def run(self) -> str:
                return str(self.x)

        class MyMCP(MCPView):
            name = "test"
            tools = [Weird]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Weird", "arguments": {"x": 1}}),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "1"

    def test_integral_float_accepted_for_integer(self) -> None:
        # `5.0` is a valid integer per JSON Schema 2020-12.
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request(
                "tools/call", {"name": "Add", "arguments": {"a": 5.0, "b": 3}}
            ),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "8.0"

    def test_non_integral_float_rejected_for_integer(self) -> None:
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request(
                "tools/call", {"name": "Add", "arguments": {"a": 5.5, "b": 3}}
            ),
        )
        assert response["result"]["isError"] is True
        assert "'a' must be an integer" in response["result"]["content"][0]["text"]

    def test_unexpected_kwarg_rejected_downstream(self) -> None:
        # All required args present plus an extra kwarg: validation is permissive
        # on unmodeled props, so the extra is caught by the __init__ TypeError.
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request(
                "tools/call",
                {"name": "Add", "arguments": {"a": 1, "b": 2, "extra": 3}},
            ),
        )
        assert response["result"]["isError"] is True
        text = response["result"]["content"][0]["text"]
        assert "Invalid arguments" in text
        assert "extra" in text

    def test_list_reports_all_bad_items(self) -> None:
        class Sum(MCPTool):
            def __init__(self, ids: list[int]):
                self.ids = ids

            def run(self) -> str:
                return str(sum(self.ids))

        class MyMCP(MCPView):
            name = "test"
            tools = [Sum]

        response = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call", {"name": "Sum", "arguments": {"ids": ["a", 1, "b"]}}
            ),
        )
        assert response["result"]["isError"] is True
        text = response["result"]["content"][0]["text"]
        assert "'ids[0]'" in text
        assert "'ids[2]'" in text

    def test_malformed_property_schema_is_permissive(self) -> None:
        # A hand-written input_schema with a shorthand (non-dict) property value
        # must not crash validation into a server error — stay permissive.
        class Custom(MCPTool):
            input_schema = {
                "type": "object",
                "properties": {"q": "string"},  # malformed: should be a dict
            }

            def __init__(self, q: str):
                self.q = q

            def run(self) -> str:
                return self.q

        class MyMCP(MCPView):
            name = "test"
            tools = [Custom]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Custom", "arguments": {"q": "hi"}}),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "hi"

    def test_hand_written_schema_keywords_are_permissive(self) -> None:
        # A tool overriding `input_schema` with keywords we don't model
        # (`oneOf`) must not be falsely rejected — we validate what we can and
        # pass the rest through to `run()`.
        class Custom(MCPTool):
            input_schema = {
                "type": "object",
                "properties": {"value": {"oneOf": [{"type": "string"}]}},
            }

            def __init__(self, value: Any):
                self.value = value

            def run(self) -> str:
                return str(self.value)

        class MyMCP(MCPView):
            name = "test"
            tools = [Custom]

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Custom", "arguments": {"value": 42}}),
        )
        assert "isError" not in response["result"]
        assert response["result"]["content"][0]["text"] == "42"

    def test_var_keyword_tool_accepts_arbitrary_args(self) -> None:
        # A **kwargs tool accepts arbitrary extra arguments — the synthetic
        # `kwargs` param must not be advertised as a required property, or
        # validation would reject every real call.
        class Flexible(MCPTool):
            def __init__(self, **kwargs):  # noqa: ANN003
                self.kwargs = kwargs

            def run(self) -> dict:
                return self.kwargs

        class MyMCP(MCPView):
            name = "test"
            tools = [Flexible]

        assert Flexible.input_schema is not None
        assert Flexible.input_schema["properties"] == {}
        assert "required" not in Flexible.input_schema

        response = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Flexible", "arguments": {"foo": 1}}),
        )
        assert "isError" not in response["result"]

    def test_named_plus_var_keyword_validates_named_only(self) -> None:
        class Flexible(MCPTool):
            def __init__(self, name: str, **extra):  # noqa: ANN003
                self.name = name
                self.extra = extra

            def run(self) -> str:
                return self.name

        class MyMCP(MCPView):
            name = "test"
            tools = [Flexible]

        schema = Flexible.input_schema
        assert schema is not None
        assert schema["required"] == ["name"]
        assert "extra" not in schema["properties"]

        # Wrong-typed named arg still rejected...
        bad = _call(
            _instantiate(MyMCP),
            _make_request("tools/call", {"name": "Flexible", "arguments": {"name": 5}}),
        )
        assert bad["result"]["isError"] is True

        # ...but a named arg plus arbitrary extras passes.
        ok = _call(
            _instantiate(MyMCP),
            _make_request(
                "tools/call",
                {"name": "Flexible", "arguments": {"name": "x", "y": 2}},
            ),
        )
        assert "isError" not in ok["result"]

    def test_non_object_arguments_rejected(self) -> None:
        response = _call(
            _instantiate(self._add_mcp()),
            _make_request("tools/call", {"name": "Add", "arguments": [1, 2]}),
        )
        assert response["result"]["isError"] is True
        assert "must be an object" in response["result"]["content"][0]["text"]


class TestToolMetadata:
    def test_tool_subclass_name_defaults_to_classname(self) -> None:
        class Greet(MCPTool):
            """Say hello."""

            def __init__(self, name: str):
                self.name = name

            def run(self) -> str:
                return f"Hello, {self.name}!"

        class MyMCP(MCPView):
            name = "test"
            tools = [Greet]

        mcp = _instantiate(MyMCP)
        tools = _call(mcp, _make_request("tools/list"))["result"]["tools"]
        assert tools[0]["name"] == "Greet"

    def test_tool_explicit_name_and_description(self) -> None:
        class Greet(MCPTool):
            name = "say_hello"
            description = "Greet a user by name."

            def __init__(self, name: str):
                self.name = name

            def run(self) -> str:
                return f"Hello, {self.name}!"

        class MyMCP(MCPView):
            name = "test"
            tools = [Greet]

        mcp = _instantiate(MyMCP)
        tools = _call(mcp, _make_request("tools/list"))["result"]["tools"]
        assert tools[0]["name"] == "say_hello"
        assert tools[0]["description"] == "Greet a user by name."

    def test_tool_without_init_has_empty_schema(self) -> None:
        class WhoAmI(MCPTool):
            """Return a greeting."""

            def run(self) -> str:
                return "hi"

        class MyMCP(MCPView):
            name = "test"
            tools = [WhoAmI]

        mcp = _instantiate(MyMCP)
        tools = _call(mcp, _make_request("tools/list"))["result"]["tools"]
        assert tools[0]["inputSchema"]["properties"] == {}


class TestToolAuthorization:
    def test_allowed_for_override_hides_and_rejects(self) -> None:
        class AdminTool(MCPTool):
            @classmethod
            def allowed_for(cls, mcp: Any) -> bool:
                user = getattr(mcp, "user", None)
                return bool(user and user.get("is_admin"))

        class DeleteUser(AdminTool):
            def __init__(self, user_id: int):
                self.user_id = user_id

            def run(self) -> str:
                return f"deleted {self.user_id}"

        class MyMCP(MCPView):
            name = "test"
            tools = [DeleteUser]

        mcp = _instantiate(MyMCP)
        # No user → hidden
        assert _call(mcp, _make_request("tools/list"))["result"]["tools"] == []
        # Call also rejected
        response = _call(
            mcp,
            _make_request(
                "tools/call", {"name": "DeleteUser", "arguments": {"user_id": 1}}
            ),
        )
        assert response["result"]["isError"] is True

        # With admin → visible and callable
        mcp.user = {"is_admin": True}  # ty: ignore[unresolved-attribute]
        assert len(_call(mcp, _make_request("tools/list"))["result"]["tools"]) == 1
        response = _call(
            mcp,
            _make_request(
                "tools/call", {"name": "DeleteUser", "arguments": {"user_id": 1}}
            ),
        )
        assert response["result"]["content"][0]["text"] == "deleted 1"

    def test_get_tools_override_for_cross_cutting_filter(self) -> None:
        """Override get_tools() to filter across all tools."""

        class PublicTool(MCPTool):
            def run(self) -> str:
                return "ok"

        class MyMCP(MCPView):
            name = "test"
            tools = [PublicTool]

            def get_tools(self):
                return []  # lock everything down

        mcp = _instantiate(MyMCP)
        assert _call(mcp, _make_request("tools/list"))["result"]["tools"] == []


class TestSchemaGeneration:
    def test_primitives(self) -> None:
        class Fn(MCPTool):
            def __init__(self, a: str, b: int, c: float, d: bool):
                pass

            def run(self) -> str:
                return ""

        class MyMCP(MCPView):
            name = "test"
            tools = [Fn]

        schema = _instantiate(MyMCP).tools[0].input_schema
        assert schema is not None
        assert schema["properties"]["a"]["type"] == "string"
        assert schema["properties"]["b"]["type"] == "integer"
        assert schema["properties"]["c"]["type"] == "number"
        assert schema["properties"]["d"]["type"] == "boolean"

    def test_list(self) -> None:
        class Fn(MCPTool):
            def __init__(self, ids: list[int]):
                pass

            def run(self) -> str:
                return ""

        class MyMCP(MCPView):
            name = "test"
            tools = [Fn]

        schema = _instantiate(MyMCP).tools[0].input_schema
        assert schema is not None
        assert schema["properties"]["ids"] == {
            "type": "array",
            "items": {"type": "integer"},
        }

    def test_literal(self) -> None:
        class Fn(MCPTool):
            def __init__(self, status: Literal["pending", "failed", "done"]):
                pass

            def run(self) -> str:
                return ""

        class MyMCP(MCPView):
            name = "test"
            tools = [Fn]

        schema = _instantiate(MyMCP).tools[0].input_schema
        assert schema is not None
        assert schema["properties"]["status"]["enum"] == ["pending", "failed", "done"]

    def test_optional(self) -> None:
        """`T | None` should stay nullable in the schema so clients can send explicit null."""

        class Fn(MCPTool):
            def __init__(self, name: str | None = None):
                pass

            def run(self) -> str:
                return ""

        class MyMCP(MCPView):
            name = "test"
            tools = [Fn]

        schema = _instantiate(MyMCP).tools[0].input_schema
        assert schema is not None
        assert schema["properties"]["name"] == {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        }
        assert "name" not in schema.get("required", [])

    def test_unannotated_param_is_required_and_permissive(self) -> None:
        """Unannotated params fall through to a permissive empty schema.

        A required-looking arg with no annotation must stay required, but its
        schema must not constrain the type — advertising `string` would make
        validation wrongly reject a dict/int the tool actually wanted (and
        treating it as optional-null would silently let clients skip it).
        """

        class Fn(MCPTool):
            def __init__(self, thing):  # noqa: ANN001
                pass

            def run(self) -> str:
                return ""

        class MyMCP(MCPView):
            name = "test"
            tools = [Fn]

        schema = _instantiate(MyMCP).tools[0].input_schema
        assert schema is not None
        assert schema["properties"]["thing"] == {}
        assert "thing" in schema["required"]


class TestDescription:
    def _tool(self, cls: type[MCPTool]) -> type[MCPTool]:
        class MyMCP(MCPView):
            name = "test"
            tools = [cls]

        return _instantiate(MyMCP).tools[0]

    def test_description_uses_class_docstring_verbatim(self) -> None:
        class CountThings(MCPTool):
            """Count things.

            A second paragraph of detail.
            """

            def __init__(self, limit: int = 10):
                self.limit = limit

            def run(self) -> str:
                return ""

        tool = self._tool(CountThings)
        assert tool.description == "Count things.\n\nA second paragraph of detail."

    def test_description_empty_when_no_docstring(self) -> None:
        class NoDoc(MCPTool):
            def __init__(self, x: int):
                self.x = x

            def run(self) -> str:
                return ""

        tool = self._tool(NoDoc)
        assert tool.description == ""
        assert tool.input_schema is not None
        assert "description" not in tool.input_schema["properties"]["x"]

    def test_description_attribute_wins_over_docstring(self) -> None:
        class Explicit(MCPTool):
            """Docstring version."""

            description = "Attribute version."

            def run(self) -> str:
                return ""

        tool = self._tool(Explicit)
        assert tool.description == "Attribute version."


class TestResources:
    def test_capabilities_include_resources_only_when_present(self) -> None:
        class EmptyMCP(MCPView):
            name = "empty"

        class WithResources(MCPView):
            name = "with-res"

            class Version(MCPResource):
                uri = "config://version"
                mime_type = "text/plain"

                def read(self) -> str:
                    return "1.0"

            resources = [Version]

        empty = _call(_instantiate(EmptyMCP), _make_request("initialize"))
        populated = _call(_instantiate(WithResources), _make_request("initialize"))

        assert "resources" not in empty["result"]["capabilities"]
        assert populated["result"]["capabilities"]["resources"] == {
            "subscribe": False,
            "listChanged": False,
        }

    def test_resources_list(self) -> None:
        class Version(MCPResource):
            """Current deployed version."""

            uri = "config://version"
            mime_type = "text/plain"

            def read(self) -> str:
                return "1.0"

        class MyMCP(MCPView):
            name = "test"
            resources = [Version]

        response = _call(_instantiate(MyMCP), _make_request("resources/list"))
        assert response["result"]["resources"] == [
            {
                "uri": "config://version",
                "name": "Version",
                "description": "Current deployed version.",
                "mimeType": "text/plain",
            }
        ]

    def test_resources_read_text(self) -> None:
        class Version(MCPResource):
            uri = "config://version"
            mime_type = "text/plain"

            def read(self) -> str:
                return "1.0"

        class MyMCP(MCPView):
            name = "test"
            resources = [Version]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "config://version"}),
        )
        assert response["result"]["contents"] == [
            {"uri": "config://version", "mimeType": "text/plain", "text": "1.0"}
        ]

    def test_resources_read_binary(self) -> None:
        class Logo(MCPResource):
            uri = "img://logo"
            mime_type = "image/png"

            def read(self) -> bytes:
                return b"\x89PNG\r\n"

        class MyMCP(MCPView):
            name = "test"
            resources = [Logo]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "img://logo"}),
        )
        entry = response["result"]["contents"][0]
        assert entry["mimeType"] == "image/png"
        assert "text" not in entry
        import base64

        assert base64.b64decode(entry["blob"]) == b"\x89PNG\r\n"

    def test_resources_read_missing_uri(self) -> None:
        class MyMCP(MCPView):
            name = "test"

        response = _call(_instantiate(MyMCP), _make_request("resources/read"))
        assert response["error"]["code"] == -32602
        assert "Missing uri" in response["error"]["message"]

    def test_resources_read_unknown_uri(self) -> None:
        class MyMCP(MCPView):
            name = "test"

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "nope://nothing"}),
        )
        assert response["error"]["code"] == -32602
        assert "Unknown resource" in response["error"]["message"]

    def test_allowed_for_filters_list_and_hides_from_read(self) -> None:
        class Hidden(MCPResource):
            uri = "secret://data"
            mime_type = "text/plain"

            @classmethod
            def allowed_for(cls, mcp: MCPView) -> bool:
                return False

            def read(self) -> str:
                return "hidden"

        class MyMCP(MCPView):
            name = "test"
            resources = [Hidden]

        mcp = _instantiate(MyMCP)
        listed = _call(mcp, _make_request("resources/list"))
        assert listed["result"]["resources"] == []

        read = _call(mcp, _make_request("resources/read", {"uri": "secret://data"}))
        # Same error as unknown URI — existence not leaked.
        assert read["error"]["code"] == -32602
        assert "Unknown resource" in read["error"]["message"]

    def test_register_resource_does_not_bleed_to_base(self) -> None:
        class Shared(MCPResource):
            uri = "a://"
            mime_type = "text/plain"

            def read(self) -> str:
                return ""

        class ChildA(MCPView):
            name = "a"

        class ChildB(MCPView):
            name = "b"

        ChildA.register_resource(Shared)

        assert Shared in ChildA.resources
        assert Shared not in MCPView.resources
        assert Shared not in ChildB.resources

    def test_resource_name_defaults_to_class_name(self) -> None:
        class CustomName(MCPResource):
            """Custom desc."""

            uri = "x://"
            mime_type = "text/plain"

            def read(self) -> str:
                return ""

        assert CustomName.name == "CustomName"
        assert CustomName.description == "Custom desc."


class TestResourceTemplates:
    def test_templates_list(self) -> None:
        class Order(MCPResource):
            """An order by ID."""

            uri_template = "orders://{order_id}"
            mime_type = "application/json"

            def __init__(self, order_id: int):
                self.order_id = order_id

            def read(self) -> str:
                return str(self.order_id)

        class MyMCP(MCPView):
            name = "test"
            resources = [Order]

        response = _call(_instantiate(MyMCP), _make_request("resources/templates/list"))
        assert response["result"]["resourceTemplates"] == [
            {
                "uriTemplate": "orders://{order_id}",
                "name": "Order",
                "description": "An order by ID.",
                "mimeType": "application/json",
            }
        ]

    def test_templates_excluded_from_resources_list(self) -> None:
        class Tpl(MCPResource):
            uri_template = "x://{id}"
            mime_type = "text/plain"

            def __init__(self, id: str):
                self.id = id

            def read(self) -> str:
                return self.id

        class MyMCP(MCPView):
            name = "test"
            resources = [Tpl]

        response = _call(_instantiate(MyMCP), _make_request("resources/list"))
        assert response["result"]["resources"] == []

    def test_read_template_resource_coerces_int(self) -> None:
        class Order(MCPResource):
            uri_template = "orders://{order_id}"
            mime_type = "text/plain"

            def __init__(self, order_id: int):
                self.order_id = order_id

            def read(self) -> str:
                return f"{self.order_id}:{type(self.order_id).__name__}"

        class MyMCP(MCPView):
            name = "test"
            resources = [Order]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "orders://42"}),
        )
        assert response["result"]["contents"][0]["text"] == "42:int"

    def test_read_template_resource_passes_string(self) -> None:
        class Thing(MCPResource):
            uri_template = "things://{slug}"
            mime_type = "text/plain"

            def __init__(self, slug: str):
                self.slug = slug

            def read(self) -> str:
                return self.slug

        class MyMCP(MCPView):
            name = "test"
            resources = [Thing]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "things://hello"}),
        )
        assert response["result"]["contents"][0]["text"] == "hello"

    def test_template_does_not_match_across_slashes(self) -> None:
        class Thing(MCPResource):
            uri_template = "x://{id}"
            mime_type = "text/plain"

            def __init__(self, id: str):
                self.id = id

            def read(self) -> str:
                return self.id

        class MyMCP(MCPView):
            name = "test"
            resources = [Thing]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "x://a/b"}),
        )
        assert response["error"]["code"] == -32602

    def test_bad_template_coercion_returns_invalid_params(self) -> None:
        class Order(MCPResource):
            uri_template = "orders://{order_id}"
            mime_type = "text/plain"

            def __init__(self, order_id: int):
                self.order_id = order_id

            def read(self) -> str:
                return str(self.order_id)

        class MyMCP(MCPView):
            name = "test"
            resources = [Order]

        response = _call(
            _instantiate(MyMCP),
            _make_request("resources/read", {"uri": "orders://notanumber"}),
        )
        assert response["error"]["code"] == -32602

    def test_setting_both_uri_and_template_is_an_error(self) -> None:
        with raises(TypeError, match="only one"):

            class Bad(MCPResource):
                uri = "a://b"
                uri_template = "a://{id}"
                mime_type = "text/plain"

                def read(self) -> str:
                    return ""


class TestToolContentTypes:
    def _call_tool(self, mcp_cls: type[MCPView], tool_name: str) -> dict:
        return _call(
            _instantiate(mcp_cls),
            _make_request("tools/call", {"name": tool_name, "arguments": {}}),
        )

    def test_image_dict_auto_encodes_bytes(self) -> None:
        class Screenshot(MCPTool):
            def run(self) -> dict:
                return {
                    "type": "image",
                    "data": b"\x89PNG",
                    "mimeType": "image/png",
                }

        class MyMCP(MCPView):
            name = "test"
            tools = [Screenshot]

        response = self._call_tool(MyMCP, "Screenshot")
        content = response["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "image"
        assert content[0]["mimeType"] == "image/png"
        import base64

        assert base64.b64decode(content[0]["data"]) == b"\x89PNG"

    def test_audio_dict_auto_encodes_bytes(self) -> None:
        class Beep(MCPTool):
            def run(self) -> dict:
                return {"type": "audio", "data": b"RIFF", "mimeType": "audio/wav"}

        class MyMCP(MCPView):
            name = "test"
            tools = [Beep]

        response = self._call_tool(MyMCP, "Beep")
        assert response["result"]["content"][0]["type"] == "audio"

    def test_embedded_resource_text_passes_through(self) -> None:
        class Embed(MCPTool):
            def run(self) -> dict:
                return {
                    "type": "resource",
                    "resource": {
                        "uri": "mem://thing",
                        "mimeType": "text/plain",
                        "text": "hello",
                    },
                }

        class MyMCP(MCPView):
            name = "test"
            tools = [Embed]

        response = self._call_tool(MyMCP, "Embed")
        assert response["result"]["content"][0] == {
            "type": "resource",
            "resource": {
                "uri": "mem://thing",
                "mimeType": "text/plain",
                "text": "hello",
            },
        }

    def test_embedded_resource_bytes_in_blob_auto_encodes(self) -> None:
        class Embed(MCPTool):
            def run(self) -> dict:
                return {
                    "type": "resource",
                    "resource": {
                        "uri": "mem://blob",
                        "mimeType": "application/octet-stream",
                        "blob": b"\x00\x01\x02",
                    },
                }

        class MyMCP(MCPView):
            name = "test"
            tools = [Embed]

        response = self._call_tool(MyMCP, "Embed")
        resource = response["result"]["content"][0]["resource"]
        import base64

        assert base64.b64decode(resource["blob"]) == b"\x00\x01\x02"

    def test_list_of_blocks_is_mixed_content(self) -> None:
        class Mixed(MCPTool):
            def run(self) -> list:
                return [
                    {"type": "text", "text": "here's a chart:"},
                    {"type": "image", "data": b"png", "mimeType": "image/png"},
                ]

        class MyMCP(MCPView):
            name = "test"
            tools = [Mixed]

        response = self._call_tool(MyMCP, "Mixed")
        content = response["result"]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image"

    def test_plain_string_becomes_text_block(self) -> None:
        class StringTool(MCPTool):
            def run(self) -> str:
                return "just a string"

        class MyMCP(MCPView):
            name = "test"
            tools = [StringTool]

        response = self._call_tool(MyMCP, "StringTool")
        assert response["result"]["content"] == [
            {"type": "text", "text": "just a string"}
        ]

    def test_non_content_dict_becomes_text_json(self) -> None:
        class GetData(MCPTool):
            def run(self) -> dict:
                return {"id": 1, "name": "Alice"}

        class MyMCP(MCPView):
            name = "test"
            tools = [GetData]

        response = self._call_tool(MyMCP, "GetData")
        assert response["result"]["content"][0]["type"] == "text"
        assert json.loads(response["result"]["content"][0]["text"]) == {
            "id": 1,
            "name": "Alice",
        }
