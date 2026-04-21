from __future__ import annotations

SECRET_KEY = "conformance"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES: list[str] = [
    "plain.mcp",
]
MIDDLEWARE: list[str] = []
# Allow plain HTTP and any Host header so the conformance CLI can hit us
# directly without cert/hostname fussing.
HTTPS_REDIRECT_ENABLED = False
ALLOWED_HOSTS: list[str] = []
