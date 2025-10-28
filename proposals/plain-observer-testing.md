# plain-observer

## Telemetry Capture for Tests

Add a `capture_telemetry()` context manager to enable testing of instrumentation, query counts, and performance.

### Location

`plain-observer/plain/observer/testing.py` - Lives in observer package to leverage existing infrastructure for analyzing spans (query detection, duplicate analysis, etc.)

### Control Mechanism

Add new setting:

```python
OBSERVER_SAMPLER_MODE: str = "auto"  # "auto", "always_on", "always_off"
```

- `"auto"` - Cookie/header based sampling (production default)
- `"always_on"` - Create all spans (for testing)
- `"always_off"` - No span creation

Tests set `OBSERVER_SAMPLER_MODE = "always_on"` to enable span creation.

### Example Usage

**Configure tests:**

```python
# conftest.py or test settings
OBSERVER_SAMPLER_MODE = "always_on"
```

**Use in tests:**

```python
from plain.observer.testing import capture_telemetry

def test_article_list_queries(client):
    with capture_telemetry() as telemetry:
        response = client.get("/articles/")

    assert telemetry.query_count == 3
    assert telemetry.duplicate_query_count == 0
    assert telemetry.duration_ms < 100

def test_custom_instrumentation():
    with capture_telemetry() as telemetry:
        my_function()

    # Access raw spans for manual inspection
    span_names = [s.name for s in telemetry.spans]
    assert "my_custom_span" in span_names
```

### TelemetryCapture API

- `query_count: int` - Number of database queries
- `duplicate_query_count: int` - Number of duplicate queries
- `duration_ms: float` - Total duration in milliseconds
- `spans: list[ReadableSpan]` - Raw OpenTelemetry spans for manual inspection

### Benefits

- Reuses observer infrastructure for query detection, duplicate analysis, etc.
- Setting-based control - simple, explicit opt-in
- Context manager API - clean syntax, explicit scope
- Flexible - multiple captures per test, partial captures
- Raw access - can inspect spans directly when needed

### Open Question: Storage Approach

Could we use observer's `Trace` and `Span` models **without persisting to database**?

- Collect raw OpenTelemetry spans in memory (simple list)
- Create `Trace` and `Span` model instances using `Trace.from_opentelemetry_spans()` and `Span.from_opentelemetry_span()`
- Get all the helper methods (`query_count`, `duplicate_query_count`, etc.) for free
- Just never call `.save()` - models stay in memory only

This would give us:

- Fast (no database I/O)
- Simple (no db fixture required)
- Reuses all observer infrastructure (models, analysis, helpers)
- Tests the model logic itself

Alternative would be a separate lightweight processor or reusing ObserverSpanProcessor with a test mode.
