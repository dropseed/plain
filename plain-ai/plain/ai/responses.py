from __future__ import annotations

from dataclasses import dataclass, field

from .messages import ToolUse


@dataclass
class Usage:
    """Token usage for a single request."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class AgentResponse:
    """The response from prompting an agent."""

    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""

    def __str__(self) -> str:
        return self.text


@dataclass
class StructuredResponse[T]:
    """A response with structured output parsed into a typed dict or dataclass."""

    data: T
    text: str
    usage: Usage = field(default_factory=Usage)

    def __str__(self) -> str:
        return self.text


@dataclass
class StreamEvent:
    """A single event from a streaming response."""

    text: str = ""
    is_complete: bool = False
    usage: Usage | None = None
    stop_reason: str = ""
