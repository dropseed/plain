# Whether to redirect the original asset path to the fingerprinted path.
ASSETS_REDIRECT_ORIGINAL: bool = True

# If assets are served by a CDN, use this URL to prefix asset paths.
# Ex. "https://cdn.example.com/assets/"
ASSETS_CDN_URL: str = ""

# Whether to log 304 Not Modified responses for assets in the access log.
# Disabled by default to reduce noise from conditional requests.
ASSETS_LOG_304: bool = False
