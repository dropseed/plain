from __future__ import annotations

import html
from collections.abc import Generator

from plain.http import StreamingResponse

from .agents import Agent
from .messages import Message


def agent_sse_response(
    agent: Agent,
    prompt: str,
    *,
    messages: list[Message] | None = None,
    provider: str | None = None,
    model: str | None = None,
    event_name: str = "message",
    wrap_html: str = "",
) -> StreamingResponse:
    """
    Stream an agent's response as Server-Sent Events.

    Returns a ``StreamingResponse`` that emits SSE-formatted events,
    ready to be consumed by HTMX's SSE extension.

    Args:
        agent: The agent to prompt.
        prompt: The user's prompt text.
        messages: Optional conversation history.
        provider: Override the provider name.
        model: Override the model name.
        event_name: The SSE event name (default "message", matches sse-swap).
        wrap_html: Optional HTML tag to wrap each chunk in (e.g. "span").

    Example view::

        class ChatView(View):
            def post(self):
                prompt = self.request.POST["prompt"]
                agent = SupportAgent()
                return agent_sse_response(agent, prompt)

    Example template::

        <div hx-ext="sse" sse-connect="/chat/stream" sse-swap="message">
            <!-- tokens appear here as they stream -->
        </div>
    """

    def generate() -> Generator[str]:
        for event in agent.stream(
            prompt,
            messages=messages,
            provider=provider,
            model=model,
        ):
            if event.text:
                data = _format_chunk(event.text, wrap_html)
                yield _sse_encode(data, event_name)

            if event.is_complete:
                yield _sse_encode("", "done")

    return StreamingResponse(
        generate(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _format_chunk(text: str, wrap_html: str) -> str:
    """Format a text chunk, optionally wrapping in an HTML tag."""
    escaped = html.escape(text)
    # Preserve newlines as <br> for HTML rendering
    escaped = escaped.replace("\n", "<br>")
    if wrap_html:
        return f"<{wrap_html}>{escaped}</{wrap_html}>"
    return escaped


def _sse_encode(data: str, event: str = "message") -> str:
    """Encode data as an SSE event string."""
    lines = [f"event: {event}"]
    for line in data.split("\n"):
        lines.append(f"data: {line}")
    lines.append("\n")
    return "\n".join(lines)
