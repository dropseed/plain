import re

from plain.testing import Client, override_settings
from plain.testing.otel import tracer_provider_for_capturing


def install_real_tracing() -> None:
    """Install a real SDK TracerProvider so requests get valid, sampled spans.

    Without an SDK provider, OpenTelemetry hands out no-op spans whose context
    is invalid (all-zero trace id). The toolbar item needs a real trace id to
    build a link, so the export-link tests opt into this. connect itself
    installs no provider in a test run.

    It is the provider `capture_spans()` uses, so a test that captures spans
    can run after these.
    """
    tracer_provider_for_capturing()


def test_no_trace_button_when_export_is_not_configured():
    # The toolbar renders in DEBUG, but with no CONNECT_EXPORT_TOKEN the
    # connect item disables itself and contributes nothing.
    with override_settings(DEBUG=True):
        response = Client().get("/")
        assert response.status_code == 200
        assert b"plainframework.com/t/" not in response.body


def test_trace_button_links_to_the_dashboard():
    # The setting only decides what the toolbar shows. Nothing is exported
    # in a test run.
    install_real_tracing()
    with override_settings(
        DEBUG=True, CONNECT_EXPORT_ENABLED=True, CONNECT_EXPORT_TOKEN="test-token"
    ):
        response = Client().get("/")
        assert response.status_code == 200
        match = re.search(rb"https://plainframework\.com/t/[0-9a-f]{32}", response.body)
        assert match, f"no trace link in toolbar: {response.body!r}"


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
        assert re.search(rb"https://cloud\.example\.com/t/[0-9a-f]{32}", response.body)
