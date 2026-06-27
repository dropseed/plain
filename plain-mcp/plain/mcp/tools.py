"""The `MCPTool` base class. Subclass, define `__init__` with your args, and implement `run()`."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from .schema import build_input_schema

if TYPE_CHECKING:
    from .views import MCPView


class MCPTool(ABC):
    """Base class for MCP tools.

    Tools take their typed arguments through `__init__` (like a dataclass
    or pydantic model) and execute via `run()`. Name, description, and
    input schema are derived automatically:

    - `name` — the class name (override with `name = "..."`)
    - `description` — the class docstring (override with `description = "..."`)
    - `input_schema` — derived from `__init__`'s typed signature
      (override by setting `input_schema = {...}` for custom shapes)

        class Greet(MCPTool):
            '''Greet someone by name.'''

            def __init__(self, name: str):
                self.name = name

            def run(self) -> str:
                return f"Hello, {self.name}!"

    Tool instances have `self.mcp` set by the dispatcher before `run()`
    is called — use it to read `self.mcp.request`, and (on an authed view)
    `self.mcp.user`, `self.mcp.scopes`, etc. `self.mcp` is typed as the
    base `MCPView`; for typed access to attributes your auth mixin or
    subclass adds, re-annotate `mcp` on a per-app base tool and subclass it:

        class AppTool(MCPTool):
            mcp: AppMCP  # forward ref — resolved lazily, so order is free

    Override `allowed_for(mcp)` (as a classmethod) to filter when the
    tool is included — auth gating, feature flags, tenant checks. Filters
    run *before* instantiation, so they can't depend on the caller's args.

    To signal an expected, caller-facing failure from `run()` (bad input,
    not found, forbidden), raise `MCPToolError(message)` — the dispatcher
    returns `message` with `isError: true` and does not log it as a server
    exception. Any other exception is logged and surfaces as an opaque
    "Tool execution failed".
    """

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] | None = None

    # Set by the MCPView dispatcher before `run()` is called. Re-annotate on a
    # per-app base tool (`mcp: AppMCP`) for typed access to your view's attrs.
    mcp: MCPView

    def __init__(self) -> None:
        """Default no-arg init — override in subclasses with your typed args."""

    @abstractmethod
    def run(self) -> Any:
        """Execute the tool. Return a str, dict, list, or anything serializable."""

    @classmethod
    def allowed_for(cls, mcp: MCPView) -> bool:
        """Return False to exclude this tool from `mcp`'s toolset.

        Runs before the tool is instantiated, so implementations can only
        rely on the MCPView's class-level state (e.g. `mcp.user`, request
        headers, settings) — not on the caller's tool arguments.

        Tools that return False are hidden from `tools/list` and rejected
        from `tools/call` (as "unknown tool" — existence isn't leaked).
        """
        return True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.__dict__.get("name"):
            cls.name = cls.__name__
        if not cls.__dict__.get("description"):
            cls.description = inspect.cleandoc(cls.__doc__ or "")
        if cls.__dict__.get("input_schema") is None:
            cls.input_schema = build_input_schema(cls.__init__)
