from plain.runtime import Secret

CONNECT_EXPORT_ENABLED: bool = True  # Set to False to disable all OTEL reporting
CONNECT_EXPORT_URL: str = "https://ingest.plainframework.com"
CONNECT_EXPORT_TOKEN: Secret[str] = ""  # Auth token for the export endpoint
CONNECT_TRACE_SAMPLE_RATE: float = 1.0  # 0.0–1.0, probability of exporting a trace
CONNECT_EXPORT_LOGS: bool = True  # Set to False to disable OTLP log export
# Minimum severity exported via OTLP logs. Accepts a level name ("INFO",
# "DEBUG", ...) or the integer level value.
CONNECT_LOG_LEVEL: str = "INFO"

# Pageview tracking — injected via the {% connect_pageviews %} template tag.
# Public endpoint token; safe to expose in page HTML.
CONNECT_PAGEVIEWS_TOKEN: str = ""
# Secret key for encrypting the logged-in user id into the identity token.
CONNECT_PAGEVIEWS_IDENTITY_KEY: Secret[str] = ""
# Pageview ingest endpoint.
CONNECT_PAGEVIEWS_URL: str = "https://beacon.plainframework.com"
