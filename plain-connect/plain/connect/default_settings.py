from plain.runtime import Secret

CONNECT_EXPORT_ENABLED: bool = True  # Set to False to disable all OTEL reporting
CONNECT_EXPORT_URL: str = "https://ingest.plainframework.com"
# Base URL of the Plain Cloud web app. Used to build links back into the
# platform — the `/t/<trace_id>` trace short URL in the toolbar and the
# `/forms/<endpoint_id>` support submission URL.
CONNECT_CLOUD_URL: str = "https://plainframework.com"
CONNECT_EXPORT_TOKEN: Secret[str] = ""  # Auth token for the export endpoint
CONNECT_TRACE_SAMPLE_RATE: float = 1.0  # 0.0–1.0, probability of exporting a trace
CONNECT_EXPORT_LOGS: bool = True  # Set to False to disable OTLP log export
# Minimum severity exported via OTLP logs. Accepts a level name ("INFO",
# "DEBUG", ...) or the integer level value.
CONNECT_LOG_LEVEL: str = "INFO"

# Shared secret with the Plain Cloud platform. One value per app, used by
# every connect feature that needs to encrypt or sign — identity tokens for
# pageviews, render tokens for the support widget, future inbound message
# verification. Get the value from the App settings page on Plain Cloud.
CONNECT_SECRET_KEY: Secret[str] = ""

# Pageview tracking — injected via the {% connect_pageviews %} template tag.
# Public endpoint token; safe to expose in page HTML.
CONNECT_PAGEVIEWS_TOKEN: str = ""
# Pageview ingest endpoint.
CONNECT_PAGEVIEWS_URL: str = "https://beacon.plainframework.com"
