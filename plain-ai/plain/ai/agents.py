from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from .messages import Message
from .providers.base import Provider, get_provider
from .responses import AgentResponse, StreamEvent, StructuredResponse, Usage
from .tools import Tool


class Agent:
    """
    Base class for AI agents.

    Define an agent by subclassing and setting ``instructions`` and
    optionally ``provider_name``, ``model``, and ``tools()``.

    Example::

        class SupportAgent(Agent):
            instructions = "You are a helpful support agent."

            def tools(self):
                return [SearchDocs()]

        agent = SupportAgent()
        response = agent.prompt("How do I reset my password?")
        print(response.text)
    """

    #: The system instructions for this agent.
    instructions: str = ""

    #: The provider name (e.g. "anthropic", "openai").
    #: If not set, uses the default from settings.
    provider_name: str | None = None

    #: The model to use (e.g. "claude-sonnet-4-5-20250929", "gpt-4o").
    #: If not set, uses the provider's default.
    model: str | None = None

    #: Maximum tokens for responses.
    max_tokens: int = 4096

    #: Request timeout in seconds.
    timeout: int = 60

    #: Maximum number of tool-use loops before stopping.
    max_tool_rounds: int = 10

    def get_tools(self) -> list[Tool]:
        """Return the tools available to this agent."""
        return []

    def get_messages(self) -> list[Message]:
        """Return any conversation history to prepend to the prompt."""
        return []

    def get_provider(self) -> Provider:
        """Get the provider instance for this agent."""
        return get_provider(self.provider_name)

    def get_model(self) -> str:
        """Get the model name, falling back to the provider's default."""
        if self.model:
            return self.model

        from plain.runtime import settings

        if settings.AI_DEFAULT_MODEL:
            return settings.AI_DEFAULT_MODEL

        return self.get_provider().default_model

    def prompt(
        self,
        prompt: str,
        *,
        messages: list[Message] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> AgentResponse:
        """
        Send a prompt to the agent and return the response.

        Automatically handles tool use loops - if the model requests a tool,
        the tool is executed and the result is sent back until the model
        produces a final text response.
        """
        actual_provider = get_provider(provider) if provider else self.get_provider()
        actual_model = model or self.get_model()
        tools = self.get_tools()

        all_messages = self.get_messages()
        if messages:
            all_messages.extend(messages)
        all_messages.append(Message.user(prompt))

        total_usage = Usage()

        for _ in range(self.max_tool_rounds):
            response = actual_provider.generate_text(
                model=actual_model,
                instructions=self.instructions or None,
                messages=all_messages,
                tools=tools or None,
                max_tokens=self.max_tokens,
                timeout=self.timeout,
            )

            total_usage.input_tokens += response.usage.input_tokens
            total_usage.output_tokens += response.usage.output_tokens

            if not response.tool_uses:
                response.usage = total_usage
                return response

            # Build the assistant message with tool use blocks and execute tools
            all_messages.append(Message.assistant(response.text))

            for tool_use in response.tool_uses:
                result = self._execute_tool(tools, tool_use.name, tool_use.arguments)
                all_messages.append(Message.tool_result(tool_use.id, result))

        # Exhausted tool rounds - return the last response
        response.usage = total_usage
        return response

    def stream(
        self,
        prompt: str,
        *,
        messages: list[Message] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> Generator[StreamEvent]:
        """
        Stream the agent's response as a series of events.

        Yields ``StreamEvent`` objects with incremental text.
        The final event has ``is_complete=True``.
        """
        actual_provider = get_provider(provider) if provider else self.get_provider()
        actual_model = model or self.get_model()
        tools = self.get_tools()

        all_messages = self.get_messages()
        if messages:
            all_messages.extend(messages)
        all_messages.append(Message.user(prompt))

        yield from actual_provider.stream_text(
            model=actual_model,
            instructions=self.instructions or None,
            messages=all_messages,
            tools=tools or None,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

    def prompt_structured(
        self,
        prompt: str,
        *,
        output_schema: dict,
        messages: list[Message] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> StructuredResponse[dict]:
        """
        Prompt the agent and parse the response as structured JSON.

        The *output_schema* should be a JSON Schema dict describing the
        expected response structure.

        Returns a ``StructuredResponse`` with the parsed data available
        via ``.data``.
        """
        actual_provider = get_provider(provider) if provider else self.get_provider()
        actual_model = model or self.get_model()

        all_messages = self.get_messages()
        if messages:
            all_messages.extend(messages)

        schema_instruction = f"Respond with valid JSON matching this schema:\n{json.dumps(output_schema, indent=2)}"
        full_instructions = self.instructions
        if full_instructions:
            full_instructions += f"\n\n{schema_instruction}"
        else:
            full_instructions = schema_instruction

        all_messages.append(Message.user(prompt))

        response = actual_provider.generate_text(
            model=actual_model,
            instructions=full_instructions,
            messages=all_messages,
            output_schema=output_schema,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )

        data = json.loads(response.text)

        return StructuredResponse(
            data=data,
            text=response.text,
            usage=response.usage,
        )

    def _execute_tool(
        self, tools: list[Tool], tool_name: str, arguments: dict[str, Any]
    ) -> str:
        for tool in tools:
            if tool.name == tool_name:
                result = tool.handle(**arguments)
                return str(result)

        return f"Error: Unknown tool '{tool_name}'"


def agent(
    instructions: str = "",
    *,
    messages: list[Message] | None = None,
    tools: list[Tool] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Agent:
    """
    Create an ad-hoc agent without defining a class.

    Example::

        from plain.ai import agent

        a = agent(instructions="You are a translator. Translate to French.")
        response = a.prompt("Hello, how are you?")
    """
    instance = Agent()
    instance.instructions = instructions
    if provider:
        instance.provider_name = provider
    if model:
        instance.model = model

    original_get_messages = instance.get_messages
    original_get_tools = instance.get_tools

    if messages:

        def _get_messages():
            return list(messages)

        instance.get_messages = _get_messages  # type: ignore[assignment]
    else:
        instance.get_messages = original_get_messages

    if tools:

        def _get_tools():
            return list(tools)

        instance.get_tools = _get_tools  # type: ignore[assignment]
    else:
        instance.get_tools = original_get_tools

    return instance
