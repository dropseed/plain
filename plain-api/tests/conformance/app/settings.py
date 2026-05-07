from __future__ import annotations

SECRET_KEY = "conformance"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES: list[str] = [
    "plain.api",
]
MIDDLEWARE: list[str] = []
# Allow plain HTTP and any Host header so schemathesis can hit us
# directly without cert/hostname fussing.
HTTPS_REDIRECT_ENABLED = False
ALLOWED_HOSTS: list[str] = []

# Tell `plain api generate-openapi` which Router to walk.
API_OPENAPI_ROUTER = "app.urls.APIRouter"
