from plain.runtime import Secret

CLOUD_EXPORT_URL: str = ""  # e.g. "https://plainframework.com/otel"
CLOUD_EXPORT_TOKEN: Secret[str] = ""  # Auth token for the export endpoint
CLOUD_TRACE_SAMPLE_RATE: float = 1.0  # 0.0–1.0, probability of exporting a trace
