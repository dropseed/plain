from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

from .messages import Message
from .providers.base import Provider
from .responses import AgentResponse, StreamEvent, Usage
from .tools import Tool


class FakeProvider(Provider):
    """
    A fake provider for testing that returns canned responses.

    Example::

        from plain.ai.testing import FakeProvider, fake_provider

        fake = FakeProvider(responses=["Hello!", "Goodbye!"])

        with fake_provider(fake):
            agent = MyAgent()
            response = agent.prompt("Hi")
            assert response.text == "Hello!"

            response = agent.prompt("Bye")
            assert response.text == "Goodbye!"

        # Assert prompts were received
        assert len(fake.prompts) == 2
        assert fake.prompts[0]["prompt"] == "Hi"
    """

    default_model = "fake-model"

    def __init__(self, responses: list[str] | None = None) -> None:
        super().__init__(api_key="fake-key")
        self.responses = list(responses or ["Fake response"])
        self.prompts: list[dict] = []
        self._response_index = 0

    def _next_response(self) -> str:
        if self._response_index >= len(self.responses):
            # Cycle back to the last response
            return self.responses[-1]
        text = self.responses[self._response_index]
        self._response_index += 1
        return text

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
        # Record the prompt for assertions
        prompt_text = messages[-1].content if messages else ""
        self.prompts.append(
            {
                "prompt": prompt_text,
                "model": model,
                "instructions": instructions,
                "messages": messages,
                "tools": tools,
            }
        )

        return AgentResponse(
            text=self._next_response(),
            usage=Usage(input_tokens=10, output_tokens=20),
            stop_reason="end_turn",
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
        prompt_text = messages[-1].content if messages else ""
        self.prompts.append(
            {
                "prompt": prompt_text,
                "model": model,
                "instructions": instructions,
                "messages": messages,
                "tools": tools,
            }
        )

        text = self._next_response()
        # Emit word by word
        words = text.split(" ")
        for i, word in enumerate(words):
            prefix = " " if i > 0 else ""
            yield StreamEvent(text=prefix + word)

        yield StreamEvent(
            is_complete=True,
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=20),
        )

    def assert_prompted(self, *, times: int | None = None) -> None:
        """Assert that the provider was prompted."""
        if times is not None:
            assert len(self.prompts) == times, (
                f"Expected {times} prompts, got {len(self.prompts)}"
            )
        else:
            assert len(self.prompts) > 0, "Expected at least one prompt"

    def assert_not_prompted(self) -> None:
        """Assert that the provider was never prompted."""
        assert len(self.prompts) == 0, f"Expected no prompts, got {len(self.prompts)}"


class fake_provider:
    """
    Context manager that patches ``get_provider`` to return a fake.

    Example::

        fake = FakeProvider(responses=["Test response"])
        with fake_provider(fake):
            response = MyAgent().prompt("hello")
            assert response.text == "Test response"
    """

    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider
        self._patcher = patch(
            "plain.ai.providers.base.get_provider",
            return_value=self.provider,
        )

    def __enter__(self) -> FakeProvider:
        self._patcher.start()
        return self.provider

    def __exit__(self, *args: object) -> None:
        self._patcher.stop()
