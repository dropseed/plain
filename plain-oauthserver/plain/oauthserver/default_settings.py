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

# Whether to accept a client_id that is an HTTPS URL to a hosted metadata
# document (Client ID Metadata Documents, MCP SEP-991). Claude's connector
# uses this by default, so it is on by default.
OAUTH_SERVER_ALLOW_CLIENT_ID_METADATA_DOCUMENTS: bool = True

# Hostnames whose metadata documents may be fetched. `None` allows any public
# host; a list restricts the server to fetching only from those hosts
# (e.g. ["claude.ai"]).
OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS: list[str] | None = None
