from __future__ import annotations

from collections.abc import Generator

from ..messages import Message, MessageRole, ToolUse
from ..responses import AgentResponse, StreamEvent, Usage
from ..tools import Tool
from .base import Provider


class OpenAIProvider(Provider):
    default_model = "gpt-4o"

    def _get_client(self, timeout: int = 60):
        try:
            import openai
        except ImportError:
            raise ImportError(
                'Install the OpenAI SDK to use this provider: pip install "plain.ai[openai]"'
            )
        return openai.OpenAI(api_key=self.api_key, timeout=timeout)

    def _format_messages(
        self, messages: list[Message], instructions: str | None = None
    ) -> list[dict]:
        formatted = []

        if instructions:
            formatted.append({"role": "system", "content": instructions})

        for msg in messages:
            if msg.role == MessageRole.TOOL_RESULT:
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_use_id,  # type: ignore[attr-defined]
                        "content": msg.content,
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
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema(),
                },
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
        import json

        client = self._get_client(timeout=timeout)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._format_messages(messages, instructions),
        }

        if tools:
            kwargs["tools"] = self._format_tools(tools)

        if output_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": output_schema,
                    "strict": True,
                },
            }

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_uses = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_uses.append(
                    ToolUse(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return AgentResponse(
            text=message.content or "",
            tool_uses=tool_uses,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            stop_reason=choice.finish_reason or "",
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
            "messages": self._format_messages(messages, instructions),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            kwargs["tools"] = self._format_tools(tools)

        stream = client.chat.completions.create(**kwargs)

        for chunk in stream:
            if not chunk.choices:
                if chunk.usage:
                    yield StreamEvent(
                        is_complete=True,
                        usage=Usage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                        ),
                    )
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            if delta and delta.content:
                yield StreamEvent(text=delta.content)

            if choice.finish_reason:
                yield StreamEvent(
                    is_complete=True,
                    stop_reason=choice.finish_reason,
                )
