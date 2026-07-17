import re

from plain.test import Client, override_settings


def install_real_tracing() -> None:
    """Install a real SDK TracerProvider so requests get valid, sampled spans.

    Without an SDK provider, OpenTelemetry hands out no-op spans whose context
    is invalid (all-zero trace id). The toolbar item needs a real trace id to
    build a link, so the export-link tests opt into this. connect itself only
    installs a provider when an export token is set at startup, which the test
    settings don't do.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        trace.set_tracer_provider(TracerProvider(sampler=ALWAYS_ON))


def test_no_trace_button_when_export_is_not_configured():
    # The toolbar renders in DEBUG, but with no CONNECT_EXPORT_TOKEN the
    # connect item disables itself and contributes nothing.
    with override_settings(DEBUG=True):
        response = Client().get("/")
        assert response.status_code == 200
        assert b"plainframework.com/t/" not in response.content


def test_trace_button_links_to_the_dashboard():
    # The test suite exports PLAIN_CONNECT_EXPORT_ENABLED=false, so re-enable it.
    install_real_tracing()
    with override_settings(
        DEBUG=True, CONNECT_EXPORT_ENABLED=True, CONNECT_EXPORT_TOKEN="test-token"
    ):
        response = Client().get("/")
        assert response.status_code == 200
        match = re.search(
            rb"https://plainframework\.com/t/[0-9a-f]{32}", response.content
        )
        assert match, f"no trace link in toolbar: {response.content!r}"


def test_trace_link_uses_the_configured_cloud_url():
    install_real_tracing()
    with override_settings(
        DEBUG=True,
        CONNECT_EXPORT_ENABLED=True,
        CONNECT_EXPORT_TOKEN="test-token",
        CONNECT_CLOUD_URL="https://cloud.example.com",
    ):
        response = Client().get("/")
        assert response.status_code == 200
        assert re.search(
            rb"https://cloud\.example\.com/t/[0-9a-f]{32}", response.content
        )
