# Time in seconds before authorization codes expire.
OAUTH_SERVER_CODE_EXPIRY: int = 600

# Time in seconds before access tokens expire.
OAUTH_SERVER_ACCESS_TOKEN_EXPIRY: int = 3600

# Time in seconds before refresh tokens expire.
OAUTH_SERVER_REFRESH_TOKEN_EXPIRY: int = 60 * 60 * 24 * 30

# Whether to allow dynamic client registration (RFC 7591). MCP clients like
# Claude self-register, so this is on by default.
OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION: bool = True

# Scopes advertised in authorization server metadata. `offline_access` signals
# that refresh tokens are available.
OAUTH_SERVER_SCOPES_SUPPORTED: list[str] = ["offline_access"]
