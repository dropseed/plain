# Bearer token for authenticating MCP clients.
# Set via PLAIN_MCP_AUTH_TOKEN env var or in settings.py.
# If empty, all requests are allowed (development only).
MCP_AUTH_TOKEN: str = ""

# MCP server name reported during initialization.
MCP_SERVER_NAME: str = "plain-mcp"

# MCP server version reported during initialization.
MCP_SERVER_VERSION: str = "0.1.0"
