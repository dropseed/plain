OBSERVER_IGNORE_URL_PATTERNS: list[str] = [
    "/assets/.*",
    "/observer/.*",
    "/pageviews/.*",
    "/favicon.ico",
    "/.well-known/.*",
]
OBSERVER_TRACE_LIMIT: int = 100

# OTLP Export Settings
#
# Option 1 (recommended): DSN - a single connection string
# Format: https://<api_key>@<host>/<project_id>
# Example: "https://pk_abc123@observatory.plain.com/42"
OBSERVER_DSN: str = ""

# Option 2: Explicit endpoint and headers (for generic OTLP backends)
# Only used if OBSERVER_DSN is not set.
# Example: "https://api.honeycomb.io/v1/traces"
OBSERVER_OTLP_ENDPOINT: str = ""
OBSERVER_OTLP_HEADERS: dict[str, str] = {}

# Continue storing traces locally in addition to OTLP export
OBSERVER_LOCAL_STORAGE: bool = True

# Tail-based sampling settings
# These determine which traces are exported to the OTLP backend.
# All conditions are OR'd together - a trace is exported if ANY condition matches.

# Always export traces that contain errors
OBSERVER_EXPORT_ERRORS: bool = True

# Export traces where the root span exceeds this duration (in milliseconds)
# Set to 0 to disable slow request sampling
OBSERVER_EXPORT_SLOW_THRESHOLD_MS: int = 1000

# Export traces containing database queries exceeding this duration (in milliseconds)
# Set to 0 to disable slow query sampling
OBSERVER_EXPORT_SLOW_QUERY_MS: int = 100

# Random sample rate for remaining traces (0.0 to 1.0)
# Example: 0.01 = 1% of traces that don't match other criteria
OBSERVER_EXPORT_SAMPLE_RATE: float = 0.0
