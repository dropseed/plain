from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"


@dataclass
class Message:
    """A message in a conversation."""

    role: MessageRole
    content: str

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> Message:
        return cls(role=MessageRole.ASSISTANT, content=content)

    @classmethod
    def tool_result(cls, tool_use_id: str, content: str) -> ToolResultMessage:
        return ToolResultMessage(
            role=MessageRole.TOOL_RESULT,
            content=content,
            tool_use_id=tool_use_id,
        )


@dataclass
class ToolResultMessage(Message):
    """A message containing the result of a tool invocation."""

    tool_use_id: str = ""


@dataclass
class ToolUse:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
