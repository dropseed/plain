from plain.runtime import Secret

CONNECT_EXPORT_ENABLED: bool = True  # Set to False to disable all OTEL reporting
CONNECT_EXPORT_URL: str = "https://ingest.plainframework.com"
CONNECT_EXPORT_TOKEN: Secret[str] = ""  # Auth token for the export endpoint
CONNECT_TRACE_SAMPLE_RATE: float = 1.0  # 0.0–1.0, probability of exporting a trace
CONNECT_EXPORT_LOGS: bool = True  # Set to False to disable OTLP log export
# Minimum severity exported via OTLP logs. Accepts a level name ("INFO",
# "DEBUG", ...) or the integer level value.
CONNECT_LOG_LEVEL: str = "INFO"
