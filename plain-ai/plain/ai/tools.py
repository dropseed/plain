from __future__ import annotations

from typing import Any


class Tool:
    """
    Base class for tools that agents can use.

    Subclass this and implement `description`, `schema()`, and `handle()`.

    Example::

        class SearchDocs(Tool):
            description = "Search documentation for relevant articles"

            def schema(self) -> dict:
                return {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        }
                    },
                    "required": ["query"],
                }

            def handle(self, *, query: str) -> str:
                results = Article.query.filter(title__contains=query)[:5]
                return "\\n".join(f"- {a.title}" for a in results)
    """

    #: A short description of what this tool does (shown to the model).
    description: str = ""

    @property
    def name(self) -> str:
        """The tool name sent to the provider. Defaults to the class name."""
        return self.__class__.__name__

    def schema(self) -> dict:
        """
        Return a JSON Schema object describing the tool's parameters.

        Must return a dict with "type": "object" at the top level.
        """
        return {"type": "object", "properties": {}}

    def handle(self, **kwargs: Any) -> str:
        """
        Execute the tool with the given arguments and return a string result.

        The kwargs correspond to the properties defined in ``schema()``.
        """
        raise NotImplementedError
