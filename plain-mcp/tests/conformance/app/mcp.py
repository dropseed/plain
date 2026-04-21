"""MCP server + tools + resources for the conformance suite.

The conformance CLI exercises specific names with specific behaviors,
so the names and docstrings here are load-bearing.
"""

from __future__ import annotations

import base64
import json

from plain.mcp import MCPInvalidParams, MCPResource, MCPTool, MCPView


class TestSimpleText(MCPTool):
    """Return a fixed text response."""

    name = "test_simple_text"

    def run(self) -> str:
        return "This is a simple text response for testing."


class TestErrorHandling(MCPTool):
    """Always raise — exercises the isError response path."""

    name = "test_error_handling"

    def run(self) -> str:
        raise RuntimeError("This tool intentionally returns an error for testing")


# Smallest valid 1x1 transparent PNG.
_TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal valid WAV header — 44 bytes, no samples. Good enough for shape tests.
_TINY_WAV_BYTES = (
    b"RIFF$\x00\x00\x00WAVEfmt "
    b"\x10\x00\x00\x00\x01\x00\x01\x00"
    b"\x44\xac\x00\x00\x88X\x01\x00"
    b"\x02\x00\x10\x00"
    b"data\x00\x00\x00\x00"
)


class TestImageContent(MCPTool):
    """Return a tiny PNG as image content."""

    name = "test_image_content"

    def run(self) -> dict:
        return {"type": "image", "data": _TINY_PNG_BYTES, "mimeType": "image/png"}


class TestAudioContent(MCPTool):
    """Return a tiny WAV as audio content."""

    name = "test_audio_content"

    def run(self) -> dict:
        return {"type": "audio", "data": _TINY_WAV_BYTES, "mimeType": "audio/wav"}


class TestEmbeddedResource(MCPTool):
    """Return a single embedded-resource content block."""

    name = "test_embedded_resource"

    def run(self) -> dict:
        return {
            "type": "resource",
            "resource": {
                "uri": "test://embedded-resource",
                "mimeType": "text/plain",
                "text": "This is an embedded resource content.",
            },
        }


class TestMultipleContentTypes(MCPTool):
    """Return a mixed list of text, image, and embedded-resource blocks."""

    name = "test_multiple_content_types"

    def run(self) -> list:
        return [
            {"type": "text", "text": "Multiple content types test:"},
            {"type": "image", "data": _TINY_PNG_BYTES, "mimeType": "image/png"},
            {
                "type": "resource",
                "resource": {
                    "uri": "test://mixed-content-resource",
                    "mimeType": "application/json",
                    "text": json.dumps({"test": "data", "value": 123}),
                },
            },
        ]


class JsonSchema202012Tool(MCPTool):
    """Tool with JSON Schema 2020-12 features"""

    name = "json_schema_2020_12_tool"
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "$defs": {
            "address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                },
            },
        },
        "properties": {
            "name": {"type": "string"},
            "address": {"$ref": "#/$defs/address"},
        },
        "additionalProperties": False,
    }

    def run(self) -> str:
        return ""


class StaticText(MCPResource):
    """Static text resource for conformance"""

    uri = "test://static-text"
    mime_type = "text/plain"

    def read(self) -> str:
        return "This is the content of the static text resource."


class StaticBinary(MCPResource):
    """Static binary resource for conformance"""

    uri = "test://static-binary"
    mime_type = "image/png"

    def read(self) -> bytes:
        return _TINY_PNG_BYTES


class TemplateData(MCPResource):
    """Parametrized resource for conformance"""

    uri_template = "test://template/{id}/data"
    mime_type = "application/json"

    def __init__(self, id: str):
        self.id = id

    def read(self) -> str:
        return json.dumps(
            {"id": self.id, "templateTest": True, "data": f"Data for ID: {self.id}"}
        )


_PROMPTS = [
    {
        "name": "test_simple_prompt",
        "description": "Simple prompt for testing",
    },
    {
        "name": "test_prompt_with_arguments",
        "description": "Prompt with arguments",
        "arguments": [
            {"name": "arg1", "description": "First test argument", "required": True},
            {"name": "arg2", "description": "Second test argument", "required": True},
        ],
    },
    {
        "name": "test_prompt_with_embedded_resource",
        "description": "Prompt that embeds a resource",
        "arguments": [
            {
                "name": "resourceUri",
                "description": "URI of the resource to embed",
                "required": True,
            },
        ],
    },
    {
        "name": "test_prompt_with_image",
        "description": "Prompt that returns an image",
    },
]


class ConformanceMCP(MCPView):
    name = "plain-mcp-conformance"
    tools = [
        TestSimpleText,
        TestErrorHandling,
        TestImageContent,
        TestAudioContent,
        TestEmbeddedResource,
        TestMultipleContentTypes,
        JsonSchema202012Tool,
    ]
    resources = [StaticText, StaticBinary, TemplateData]

    def get_capabilities(self) -> dict:
        caps = super().get_capabilities()
        caps["prompts"] = {"listChanged": False}
        return caps

    def rpc_prompts_list(self, params: dict) -> dict:
        return {"prompts": _PROMPTS}

    def rpc_prompts_get(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}

        if name == "test_simple_prompt":
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "This is a simple prompt for testing.",
                        },
                    }
                ]
            }

        if name == "test_prompt_with_arguments":
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Prompt with arguments: arg1='{args.get('arg1')}',"
                                f" arg2='{args.get('arg2')}'"
                            ),
                        },
                    }
                ]
            }

        if name == "test_prompt_with_embedded_resource":
            uri = args.get("resourceUri")
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "resource",
                            "resource": {
                                "uri": uri,
                                "mimeType": "text/plain",
                                "text": "Embedded resource content for testing.",
                            },
                        },
                    },
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Please process the embedded resource above.",
                        },
                    },
                ]
            }

        if name == "test_prompt_with_image":
            data = base64.b64encode(_TINY_PNG_BYTES).decode("ascii")
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "image",
                            "data": data,
                            "mimeType": "image/png",
                        },
                    },
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Please analyze the image above.",
                        },
                    },
                ]
            }

        raise MCPInvalidParams(f"Unknown prompt: {name}")
