from __future__ import annotations

from collections.abc import Generator

from ..messages import Message, MessageRole, ToolUse
from ..responses import AgentResponse, StreamEvent, Usage
from ..tools import Tool
from .base import Provider


class AnthropicProvider(Provider):
    default_model = "claude-sonnet-4-5-20250929"

    def _get_client(self, timeout: int = 60):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                'Install the Anthropic SDK to use this provider: pip install "plain.ai[anthropic]"'
            )
        return anthropic.Anthropic(api_key=self.api_key, timeout=timeout)

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        formatted = []
        for msg in messages:
            if msg.role == MessageRole.TOOL_RESULT:
                formatted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_use_id,  # type: ignore[attr-defined]
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.role == MessageRole.ASSISTANT:
                formatted.append({"role": "assistant", "content": msg.content})
            else:
                formatted.append({"role": "user", "content": msg.content})
        return formatted

    def _format_tools(self, tools: list[Tool]) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.schema(),
            }
            for tool in tools
        ]

    def generate_text(
        self,
        *,
        model: str,
        instructions: str | None = None,
        messages: list[Message],
        tools: list[Tool] | None = None,
        output_schema: dict | None = None,
        max_tokens: int = 4096,
        timeout: int = 60,
    ) -> AgentResponse:
        client = self._get_client(timeout=timeout)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._format_messages(messages),
        }

        if instructions:
            kwargs["system"] = instructions

        if tools:
            kwargs["tools"] = self._format_tools(tools)

        response = client.messages.create(**kwargs)

        text_parts = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(
                    ToolUse(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )

        return AgentResponse(
            text="\n".join(text_parts),
            tool_uses=tool_uses,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason or "",
        )

    def stream_text(
        self,
        *,
        model: str,
        instructions: str | None = None,
        messages: list[Message],
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        timeout: int = 60,
    ) -> Generator[StreamEvent]:
        client = self._get_client(timeout=timeout)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._format_messages(messages),
        }

        if instructions:
            kwargs["system"] = instructions

        if tools:
            kwargs["tools"] = self._format_tools(tools)

        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield StreamEvent(text=text)

            response = stream.get_final_message()
            yield StreamEvent(
                is_complete=True,
                stop_reason=response.stop_reason or "",
                usage=Usage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                ),
            )
