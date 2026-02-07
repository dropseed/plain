from __future__ import annotations

from collections.abc import Generator

from ..messages import Message
from ..responses import AgentResponse, StreamEvent
from ..tools import Tool


class Provider:
    """
    Abstract base for LLM providers.

    Each provider implements the translation between Plain's agent/tool/message
    types and the provider's native API.
    """

    #: The default model to use if none is specified.
    default_model: str = ""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

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
        """Generate a text response (single turn, no tool loop)."""
        raise NotImplementedError

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
        """Stream text events as a generator."""
        raise NotImplementedError


def get_provider(name: str | None = None, api_key: str | None = None) -> Provider:
    """
    Get a provider instance by name.

    If *name* is ``None``, the default from settings is used.
    If *api_key* is ``None``, the key from settings is used.
    """
    from plain.runtime import settings

    if name is None:
        name = settings.AI_DEFAULT_PROVIDER

    if name == "anthropic":
        from .anthropic import AnthropicProvider

        if api_key is None:
            api_key = settings.AI_ANTHROPIC_API_KEY
        return AnthropicProvider(api_key=api_key)
    elif name == "openai":
        from .openai import OpenAIProvider

        if api_key is None:
            api_key = settings.AI_OPENAI_API_KEY
        return OpenAIProvider(api_key=api_key)
    else:
        raise ValueError(f"Unknown AI provider: {name!r}")
